<?php

namespace App\Console\Commands;

use App\Models\ActivityLog;
use App\Services\TradingService;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\File;
use Illuminate\Support\Facades\Http;

class TradingEveningReviewCommand extends Command
{
    protected $signature = 'trading:evening-review {--date=}';

    protected $description = 'AI evening learning review from privacy-safe journal aggregates (never places trades)';

    public function handle(TradingService $trading): int
    {
        $day = $this->option('date') ?: now('UTC')->toDateString();

        try {
            // Aggregates only — no prices, stakes, contracts, or reason strings
            $payloadResp = $trading->getEveningAiPayload($day);
            $payload = $payloadResp['data'] ?? $payloadResp;

            $aiUrl = rtrim(config('services.ai.url', 'http://localhost:8001'), '/');
            $aiKey = config('services.ai.api_key', '');
            $request = Http::timeout(120);
            if ($aiKey) {
                $request = $request->withToken($aiKey);
            }
            $response = $request->post("{$aiUrl}/trading/evening-review", $payload);

            if (! $response->successful()) {
                $this->warn('AI agent unavailable — writing stats-only evening review');
                $markdown = $this->statsOnlyMarkdown($payload, $day);
                $body = [
                    'date' => $day,
                    'markdown' => $markdown,
                    'summary' => 'Stats-only fallback (AI unavailable)',
                ];
            } else {
                $body = $response->json() ?? [];
                $body['date'] = $body['date'] ?? $day;
                if (empty($body['markdown'])) {
                    $body['markdown'] = $this->statsOnlyMarkdown($payload, $day);
                }
            }

            try {
                $trading->saveEveningReview($body);
            } catch (\Exception $e) {
                $this->warn('Engine save failed, writing locally: '.$e->getMessage());
                $this->writeLocalReview($day, $body['markdown'] ?? '');
            }

            $this->writeLocalReview($day, $body['markdown'] ?? '');

            try {
                ActivityLog::create([
                    'user_id' => null,
                    'action' => 'trading.evening_review',
                    'entity_type' => 'trading',
                    'entity_id' => null,
                    'description' => "Evening review for {$day}",
                    'data' => [
                        'date' => $day,
                        'best_strategy' => $body['best_strategy'] ?? null,
                        'worst_strategy' => $body['worst_strategy'] ?? null,
                    ],
                ]);
            } catch (\Exception $e) {
                $this->warn('Activity log skipped: '.$e->getMessage());
            }

            $this->info("Evening review stored for {$day}");

            return self::SUCCESS;
        } catch (\Exception $e) {
            $this->error('Evening review failed: '.$e->getMessage());

            return self::FAILURE;
        }
    }

    protected function writeLocalReview(string $day, string $markdown): void
    {
        $reviewsDir = base_path('../trading-engine/reports/reviews');
        if (! File::isDirectory($reviewsDir)) {
            File::makeDirectory($reviewsDir, 0755, true);
        }
        File::put($reviewsDir.'/evening_review_'.$day.'.md', $markdown);
    }

    protected function statsOnlyMarkdown(array $payload, string $day): string
    {
        $summary = $payload['summary'] ?? [];
        $byStrategy = $payload['by_strategy'] ?? [];
        $byHour = $payload['by_hour_utc'] ?? [];
        $lines = [
            "# Evening Review — {$day}",
            '',
            '## Summary (aggregates only)',
            '- Closed: '.($summary['trades_closed'] ?? 0),
            '- Win rate: '.($summary['win_rate_pct'] ?? 0).'%',
            '- Avg PnL/trade: '.($summary['avg_pnl_per_trade'] ?? 0),
            '- Skips: '.($summary['skips'] ?? 0),
            '- Avg SL pips: '.($summary['avg_sl_distance_pips'] ?? 'n/a'),
            '- Avg TP pips: '.($summary['avg_tp_distance_pips'] ?? 'n/a'),
            '',
            '## By strategy',
        ];
        foreach ($byStrategy as $sid => $meta) {
            $lines[] = '- **'.$sid.'**: trades='.($meta['trades'] ?? 0)
                .' win_rate='.($meta['win_rate_pct'] ?? 0).'%'
                .' avg_pnl='.($meta['avg_pnl'] ?? 0);
        }
        $lines[] = '';
        $lines[] = '## By hour (UTC)';
        foreach ($byHour as $hour => $meta) {
            $lines[] = "- **{$hour}h**: trades=".($meta['trades'] ?? 0)
                .' win_rate='.($meta['win_rate_pct'] ?? 0).'%';
        }
        $lines[] = '';
        $lines[] = '_Stats-only review (AI unavailable). No prices, stakes, or account data were shared._';

        return implode("\n", $lines);
    }
}
