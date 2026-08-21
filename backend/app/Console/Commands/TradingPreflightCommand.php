<?php

namespace App\Console\Commands;

use App\Models\ActivityLog;
use App\Services\TradingService;
use Illuminate\Console\Command;

class TradingPreflightCommand extends Command
{
    protected $signature = 'trading:preflight';

    protected $description = 'Run daily trading preflight on the analysis engine';

    public function handle(TradingService $trading): int
    {
        if (now('UTC')->isWeekend()) {
            $this->info('Weekend — skipping FX preflight (markets closed)');

            return self::SUCCESS;
        }

        try {
            $result = $trading->runPreflight();
            $armed = $result['analysis_armed'] ?? false;
            $decision = $result['data']['decision'] ?? 'NO-GO';

            ActivityLog::create([
                'user_id' => null,
                'action' => 'trading.preflight',
                'entity_type' => 'trading',
                'entity_id' => null,
                'data' => $result,
                'description' => "Trading preflight: {$decision}, armed=" . ($armed ? 'yes' : 'no'),
            ]);

            $this->info("Preflight complete: {$decision}, armed=" . ($armed ? 'yes' : 'no'));
            return self::SUCCESS;
        } catch (\Exception $e) {
            $this->error('Preflight failed: ' . $e->getMessage());
            return self::FAILURE;
        }
    }
}
