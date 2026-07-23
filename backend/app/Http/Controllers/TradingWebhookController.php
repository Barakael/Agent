<?php

namespace App\Http\Controllers;

use App\Models\ActivityLog;
use App\Models\TradingAnalysisDecision;
use App\Services\TradingService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\File;
use Illuminate\Support\Facades\Validator;

class TradingWebhookController extends Controller
{
    private const STRATEGY_IDS = [
        'macd_rsi',
        'ema_pullback',
        'rsi_divergence',
        'bollinger_mean_reversion',
        'engulfing_htf',
        'bias_swing',
    ];

    public function __construct(protected TradingService $trading)
    {
    }

    public function dailyContext(Request $request)
    {
        $status = [];
        $metrics = [];
        $preflight = [];
        $plan = null;

        try {
            $status = $this->trading->status();
        } catch (\Exception $e) {
            $status = ['error' => 'unreachable'];
        }
        try {
            $metrics = $this->trading->metrics();
        } catch (\Exception $e) {
            $metrics = [];
        }
        try {
            $preflight = $this->trading->getPreflightLatest();
        } catch (\Exception $e) {
            $preflight = [];
        }
        try {
            $planResp = $this->trading->getActivePlan();
            $plan = $planResp['data'] ?? null;
        } catch (\Exception $e) {
            $plan = null;
        }

        $report = $this->latestDailyReport();
        $decision = TradingAnalysisDecision::query()->latest()->first();

        $marketBrief = null;
        try {
            $briefResp = $this->trading->getMarketBrief();
            $marketBrief = $briefResp['data'] ?? $briefResp;
        } catch (\Exception $e) {
            $marketBrief = ['error' => 'unreachable', 'message' => $e->getMessage()];
        }

        return response()->json([
            'data' => [
                'utc_date' => now('UTC')->toDateString(),
                'status' => $status,
                'metrics' => $metrics['data'] ?? $metrics,
                'preflight' => $preflight['data'] ?? $preflight,
                'active_plan' => $plan,
                'latest_report' => $report,
                'latest_ai_decision' => $decision,
                'market_brief' => $marketBrief,
                'allowlist_pairs' => ['frxEURUSD', 'frxGBPUSD', 'frxUSDJPY', 'frxAUDUSD'],
                'strategy_win_rates' => $status['strategy_win_rates'] ?? [],
                'armed_strategies' => $status['armed_strategies'] ?? [],
                'clamps' => [
                    'sl_pips' => [5, 50],
                    'tp_pips' => [10, 100],
                    'swing_sl_pips' => [5, 80],
                    'swing_tp_pips' => [10, 200],
                    'risk_percent_max' => 2.0,
                    'max_stake_usd_ceiling' => 50,
                    'strategy_ids' => self::STRATEGY_IDS,
                    'trade_modes' => ['pattern', 'bias'],
                    'hold_policies' => ['intraday', 'swing'],
                    'min_strategy_win_rate' => 70,
                ],
            ],
        ]);
    }

    public function dailyPlan(Request $request)
    {
        $validator = Validator::make($request->all(), [
            'date' => 'required|date_format:Y-m-d',
            'pairs' => 'required|array|min:1',
            'pairs.*' => 'required|string|in:frxEURUSD,frxGBPUSD,frxUSDJPY,frxAUDUSD',
            'strategy_id' => 'sometimes|string|in:'.implode(',', self::STRATEGY_IDS),
            'enabled_strategies' => 'sometimes|array|max:5',
            'enabled_strategies.*' => 'string|in:'.implode(',', self::STRATEGY_IDS),
            'trade_mode' => 'sometimes|string|in:pattern,bias',
            'directional_bias' => 'sometimes|string|in:buy,sell,neutral',
            'hold_policy' => 'sometimes|string|in:intraday,swing',
            'max_hold_days' => 'sometimes|integer|min:1|max:14',
            'sl_pips' => 'sometimes|integer|min:5|max:80',
            'tp_pips' => 'sometimes|integer|min:10|max:200',
            'risk_percent' => 'sometimes|numeric|gt:0|max:2',
            'max_stake_usd' => 'sometimes|numeric|gt:0|max:50',
            'confidence' => 'sometimes|integer|min:0|max:100',
            'notes' => 'sometimes|string|max:2000',
            'source' => 'sometimes|string|max:64',
        ]);

        if ($validator->fails()) {
            ActivityLog::create([
                'user_id' => null,
                'action' => 'trading.daily_plan.rejected',
                'entity_type' => 'trading',
                'data' => ['errors' => $validator->errors()->toArray(), 'body' => $request->all()],
                'ip_address' => $request->ip(),
                'description' => 'Daily plan rejected by validation',
            ]);

            return response()->json(['message' => 'Validation failed', 'errors' => $validator->errors()], 422);
        }

        $data = $validator->validated();
        $data['trade_mode'] = $data['trade_mode'] ?? 'pattern';
        $data['directional_bias'] = $data['directional_bias'] ?? 'neutral';
        $data['hold_policy'] = $data['hold_policy'] ?? ($data['trade_mode'] === 'bias' ? 'swing' : 'intraday');
        $data['max_hold_days'] = $data['max_hold_days'] ?? ($data['trade_mode'] === 'bias' ? 5 : 1);
        $data['strategy_id'] = $data['strategy_id'] ?? 'macd_rsi';
        $data['enabled_strategies'] = $data['enabled_strategies'] ?? [$data['strategy_id']];
        $data['sl_pips'] = $data['sl_pips'] ?? 15;
        $data['tp_pips'] = $data['tp_pips'] ?? 30;
        $data['risk_percent'] = min((float) ($data['risk_percent'] ?? 1.5), 2.0);
        $data['max_stake_usd'] = min((float) ($data['max_stake_usd'] ?? 25), 50);
        $data['confidence'] = (int) ($data['confidence'] ?? 50);
        $data['notes'] = $data['notes'] ?? '';
        $data['source'] = $data['source'] ?? 'cursor-automation';

        if ($data['trade_mode'] === 'bias' && ($data['directional_bias'] ?? 'neutral') === 'neutral') {
            return response()->json(['message' => 'directional_bias required for bias trade_mode'], 422);
        }

        $slMax = ($data['hold_policy'] === 'swing' || $data['trade_mode'] === 'bias') ? 80 : 50;
        $tpMax = ($data['hold_policy'] === 'swing' || $data['trade_mode'] === 'bias') ? 200 : 100;
        $data['sl_pips'] = min((int) $data['sl_pips'], $slMax);
        $data['tp_pips'] = min((int) $data['tp_pips'], $tpMax);

        if ($data['tp_pips'] < $data['sl_pips']) {
            return response()->json(['message' => 'tp_pips must be >= sl_pips'], 422);
        }

        try {
            $result = $this->trading->putActivePlan($data);
        } catch (\Exception $e) {
            ActivityLog::create([
                'user_id' => null,
                'action' => 'trading.daily_plan.error',
                'entity_type' => 'trading',
                'data' => ['error' => $e->getMessage(), 'body' => $data],
                'ip_address' => $request->ip(),
                'description' => 'Daily plan engine error',
            ]);

            return response()->json(['message' => $e->getMessage()], 502);
        }

        ActivityLog::create([
            'user_id' => null,
            'action' => 'trading.daily_plan.accepted',
            'entity_type' => 'trading',
            'data' => $result,
            'ip_address' => $request->ip(),
            'description' => 'Daily plan accepted for '.$data['date'],
        ]);

        $reviewsDir = base_path('../trading-engine/reports/reviews');
        if (! File::isDirectory($reviewsDir)) {
            File::makeDirectory($reviewsDir, 0755, true);
        }
        $reviewPath = $reviewsDir.'/review_'.$data['date'].'.md';
        $notes = $data['notes'] !== '' ? $data['notes'] : 'Plan submitted by automation.';
        File::put($reviewPath, "# Trading review {$data['date']}\n\n{$notes}\n\n```json\n".json_encode($data, JSON_PRETTY_PRINT)."\n```\n");

        return response()->json($result);
    }

    protected function latestDailyReport(): ?array
    {
        $dir = base_path('../trading-engine/reports/demo');
        if (! File::isDirectory($dir)) {
            return null;
        }
        $files = collect(File::files($dir))
            ->filter(fn ($f) => str_starts_with($f->getFilename(), 'daily_') && str_ends_with($f->getFilename(), '.json'))
            ->sortByDesc(fn ($f) => $f->getFilename())
            ->values();
        if ($files->isEmpty()) {
            return null;
        }
        $raw = File::get($files->first()->getPathname());
        $decoded = json_decode($raw, true);

        return is_array($decoded) ? $decoded : null;
    }
}
