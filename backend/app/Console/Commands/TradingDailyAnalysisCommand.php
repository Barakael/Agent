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
            $preflight = [];
            $metrics = [];
            $status = [];
            try {
                $preflight = $trading->getPreflightLatest();
            } catch (\Exception $e) {
                $this->warn('preflight unavailable: '.$e->getMessage());
            }
            try {
                $metrics = $trading->metrics();
            } catch (\Exception $e) {
                $this->warn('metrics unavailable: '.$e->getMessage());
            }
            try {
                $status = $trading->status();
            } catch (\Exception $e) {
                $this->warn('status unavailable: '.$e->getMessage());
            }
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

            // Cursor Automation owns BUY/SELL plans. This cron must NEVER post a
            // directional thesis (especially not the old hardcoded buy fallback).
            // Only post stand-aside when there is no cursor-automation plan for today.
            $this->syncStandAsideIfNeeded($trading);

            $this->info("Daily analysis stored: {$record->decision}");

            return self::SUCCESS;
        } catch (\Exception $e) {
            $this->error('Daily analysis failed: '.$e->getMessage());
            // Still try to clear fake directional plans if Cursor has not posted.
            try {
                $this->syncStandAsideIfNeeded($trading);
            } catch (\Exception $inner) {
                $this->warn('Stand-aside after failure also failed: '.$inner->getMessage());
            }

            return self::FAILURE;
        }
    }

    /**
     * Leave Cursor plans alone; otherwise post neutral awaiting_cursor_plan.
     */
    protected function syncStandAsideIfNeeded(TradingService $trading): void
    {
        $today = now()->utc()->toDateString();
        $existing = null;
        try {
            $existing = $trading->getActivePlan();
        } catch (\Exception $e) {
            $this->warn('Could not read active plan: '.$e->getMessage());
        }
        $active = is_array($existing) ? ($existing['data'] ?? $existing['stored'] ?? null) : null;
        $activeSource = is_array($active) ? strtolower((string) ($active['source'] ?? '')) : '';
        $activeDate = is_array($active) ? (string) ($active['date'] ?? '') : '';
        $isCursorToday = $activeDate === $today
            && str_starts_with($activeSource, 'cursor');

        if ($isCursorToday) {
            $this->info('Leaving Cursor Automation plan in place (source='.$activeSource.')');

            return;
        }

        $trading->putActivePlan([
            'date'             => $today,
            'trade_mode'       => 'pattern',
            'directional_bias' => 'neutral',
            'pairs'            => ['frxEURUSD'],
            'hold_policy'      => 'intraday',
            'sl_pips'          => 15,
            'tp_pips'          => 30,
            'notes'            => 'awaiting_cursor_plan',
            'source'           => 'daily-analysis-cron',
        ]);
        $this->info('Stand-aside posted (awaiting_cursor_plan)');
    }

    /**
     * Log-only recommendation when the local AI agent is down.
     * Must never invent buy/sell — Cursor Automation owns direction.
     */
    protected function fallbackRecommendation(array $marketBrief, string $decision): array
    {
        return [
            'recommended_trade_mode' => 'pattern',
            'pairs' => ['frxEURUSD'],
            'enabled_strategies' => [],
            'directional_bias' => 'neutral',
            'hold_policy' => 'intraday',
            'confidence' => 0,
            'notes' => 'awaiting_cursor_plan — local AI unavailable; no directional fallback',
        ];
    }
}
