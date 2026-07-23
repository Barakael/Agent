<?php

namespace App\Console\Commands;

use App\Models\ActivityLog;
use App\Models\TradingAnalysisDecision;
use App\Services\TradingService;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Http;

class TradingDailyAnalysisCommand extends Command
{
    protected $signature = 'trading:daily-analysis';

    protected $description = 'Run AI daily synthesis from market brief + preflight (plan recommendation)';

    public function handle(TradingService $trading): int
    {
        try {
            $preflight = $trading->getPreflightLatest();
            $metrics = $trading->metrics();
            $status = $trading->status();
            $marketBrief = [];
            try {
                $briefResp = $trading->getMarketBrief();
                $marketBrief = $briefResp['data'] ?? $briefResp;
            } catch (\Exception $e) {
                $this->warn('market_brief unavailable: '.$e->getMessage());
            }

            $payload = [
                'preflight' => $preflight['data'] ?? $preflight,
                'metrics' => $metrics['data'] ?? $metrics,
                'status' => $status,
                'market_brief' => $marketBrief,
            ];

            $aiUrl = rtrim(config('services.ai.url', 'http://localhost:8001'), '/');
            $aiKey = config('services.ai.api_key', '');
            $request = Http::timeout(120);
            if ($aiKey) {
                $request = $request->withToken($aiKey);
            }
            $response = $request->post("{$aiUrl}/trading/daily-analysis", $payload);

            if (! $response->successful()) {
                $this->warn('AI agent unavailable — storing rule-based decision from preflight');
                $decision = ($preflight['data']['decision'] ?? 'NO-GO') === 'GO' ? 'GO' : 'NO-GO';
                $recommendation = $this->fallbackRecommendation($marketBrief, $decision);
                $record = TradingAnalysisDecision::create([
                    'decision' => $decision,
                    'summary' => 'Fallback to preflight decision (AI unavailable)',
                    'reasons' => $preflight['data']['reasons'] ?? [],
                    'risks' => [],
                    'recommendation' => $recommendation,
                    'sources' => $payload,
                    'source' => 'preflight-fallback',
                ]);
            } else {
                $body = $response->json() ?? [];
                $recommendation = $body['recommendation'] ?? [
                    'recommended_trade_mode' => $body['recommended_trade_mode'] ?? null,
                    'pairs' => $body['pairs'] ?? [],
                    'enabled_strategies' => $body['enabled_strategies'] ?? [],
                    'directional_bias' => $body['directional_bias'] ?? null,
                    'hold_policy' => $body['hold_policy'] ?? null,
                    'confidence' => $body['confidence'] ?? null,
                    'sl_pips' => $body['sl_pips'] ?? null,
                    'tp_pips' => $body['tp_pips'] ?? null,
                    'risk_percent' => $body['risk_percent'] ?? null,
                    'max_stake_usd' => $body['max_stake_usd'] ?? null,
                    'notes' => $body['notes'] ?? null,
                ];
                $record = TradingAnalysisDecision::create([
                    'decision' => $body['decision'] ?? 'NO-GO',
                    'summary' => $body['summary'] ?? '',
                    'reasons' => $body['reasons'] ?? [],
                    'risks' => $body['risks'] ?? [],
                    'recommendation' => $recommendation,
                    'sources' => $payload,
                    'source' => 'ai-agent',
                ]);
            }

            ActivityLog::create([
                'user_id' => null,
                'action' => 'trading.daily_analysis',
                'entity_type' => 'trading',
                'entity_id' => $record->id,
                'data' => $record->toArray(),
                'description' => "AI daily analysis: {$record->decision}",
            ]);

            try {
                $trading->pushAiDecision(array_merge($record->toArray(), [
                    'recommendation' => $record->recommendation ?? [],
                ]));
            } catch (\Exception $e) {
                $this->warn('Could not sync AI decision to trading engine: '.$e->getMessage());
            }

            $this->info("Daily analysis stored: {$record->decision}");

            return self::SUCCESS;
        } catch (\Exception $e) {
            $this->error('Daily analysis failed: '.$e->getMessage());

            return self::FAILURE;
        }
    }

    protected function fallbackRecommendation(array $marketBrief, string $decision): array
    {
        $fitness = $marketBrief['strategy_fitness'] ?? [];
        $armed = [];
        foreach ($fitness as $sid => $meta) {
            if (is_array($meta) && ($meta['passed'] ?? false)) {
                $armed[] = $sid;
            }
        }
        if ($decision === 'GO' && $armed !== []) {
            return [
                'recommended_trade_mode' => 'pattern',
                'pairs' => array_slice($marketBrief['constraints']['pairs_allowlist'] ?? ['frxEURUSD'], 0, 1),
                'enabled_strategies' => array_slice($armed, 0, 5),
                'directional_bias' => 'neutral',
                'hold_policy' => 'intraday',
                'confidence' => 45,
                'notes' => 'Fallback pattern recommendation',
            ];
        }

        return [
            'recommended_trade_mode' => 'bias',
            'pairs' => ['frxEURUSD'],
            'enabled_strategies' => ['bias_swing'],
            'directional_bias' => 'buy',
            'hold_policy' => 'swing',
            'confidence' => 35,
            'notes' => 'Fallback bias recommendation',
        ];
    }
}
