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

    protected $description = 'Run AI daily GO/NO-GO synthesis from trading preflight data';

    public function handle(TradingService $trading): int
    {
        try {
            $preflight = $trading->getPreflightLatest();
            $metrics = $trading->metrics();
            $status = $trading->status();

            $payload = [
                'preflight' => $preflight['data'] ?? $preflight,
                'metrics' => $metrics['data'] ?? $metrics,
                'status' => $status,
            ];

            $aiUrl = rtrim(config('services.ai.url', 'http://localhost:8001'), '/');
            $aiKey = config('services.ai.api_key', '');
            $request = Http::timeout(120);
            if ($aiKey) {
                $request = $request->withToken($aiKey);
            }
            $response = $request->post("{$aiUrl}/trading/daily-analysis", $payload);

            if (!$response->successful()) {
                $this->warn('AI agent unavailable — storing rule-based decision from preflight');
                $decision = ($preflight['data']['decision'] ?? 'NO-GO') === 'GO' ? 'GO' : 'NO-GO';
                $record = TradingAnalysisDecision::create([
                    'decision' => $decision,
                    'summary' => 'Fallback to preflight decision (AI unavailable)',
                    'reasons' => $preflight['data']['reasons'] ?? [],
                    'risks' => [],
                    'sources' => $payload,
                    'source' => 'preflight-fallback',
                ]);
            } else {
                $body = $response->json();
                $record = TradingAnalysisDecision::create([
                    'decision' => $body['decision'] ?? 'NO-GO',
                    'summary' => $body['summary'] ?? '',
                    'reasons' => $body['reasons'] ?? [],
                    'risks' => $body['risks'] ?? [],
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
                $trading->pushAiDecision($record->toArray());
            } catch (\Exception $e) {
                $this->warn('Could not sync AI decision to trading engine: ' . $e->getMessage());
            }

            $this->info("Daily analysis stored: {$record->decision}");
            return self::SUCCESS;
        } catch (\Exception $e) {
            $this->error('Daily analysis failed: ' . $e->getMessage());
            return self::FAILURE;
        }
    }
}
