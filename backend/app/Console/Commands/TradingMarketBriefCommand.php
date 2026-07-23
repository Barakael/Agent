<?php

namespace App\Console\Commands;

use App\Services\TradingService;
use Illuminate\Console\Command;

class TradingMarketBriefCommand extends Command
{
    protected $signature = 'trading:market-brief {--json : Output raw JSON only}';

    protected $description = 'Fetch and print the live multi-source market brief (what Cursor Automations see)';

    public function handle(TradingService $trading): int
    {
        try {
            $resp = $trading->getMarketBrief();
            $brief = $resp['data'] ?? $resp;
            if ($this->option('json')) {
                $this->line(json_encode($brief, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));

                return self::SUCCESS;
            }

            $this->info('Market brief as_of: '.($brief['as_of_utc'] ?? 'n/a'));
            $pairs = $brief['pairs'] ?? [];
            $this->table(
                ['Pair', 'Price', 'RSI', 'Trend', 'Signal'],
                collect($pairs)->map(function ($row, $sym) {
                    if (! is_array($row)) {
                        return [$sym, '-', '-', '-', '-'];
                    }

                    return [
                        $sym,
                        $row['price'] ?? '-',
                        $row['rsi'] ?? '-',
                        $row['trend'] ?? '-',
                        $row['signal'] ?? '-',
                    ];
                })->values()->all()
            );
            $headlines = $brief['headlines'] ?? [];
            $this->info('Headlines: '.count($headlines));
            foreach (array_slice($headlines, 0, 8) as $h) {
                $this->line(' - ['.($h['source'] ?? '?').'] '.($h['title'] ?? ''));
            }
            $cal = $brief['calendar']['upcoming_high_impact'] ?? [];
            $this->info('High-impact events (48h): '.count($cal));
            foreach (array_slice($cal, 0, 5) as $e) {
                $this->line(' - '.($e['time'] ?? '').' '.($e['currency'] ?? '').' '.($e['title'] ?? ''));
            }
            $fitness = $brief['strategy_fitness'] ?? [];
            $this->info('Strategy fitness:');
            foreach ($fitness as $sid => $meta) {
                if (! is_array($meta)) {
                    continue;
                }
                $pass = ($meta['passed'] ?? false) ? 'PASS' : 'fail';
                $this->line(sprintf(
                    ' - %s wr=%s trades=%s [%s]',
                    $sid,
                    $meta['win_rate'] ?? 0,
                    $meta['total_trades'] ?? 0,
                    $pass
                ));
            }

            return self::SUCCESS;
        } catch (\Exception $e) {
            $this->error('market-brief failed: '.$e->getMessage());

            return self::FAILURE;
        }
    }
}
