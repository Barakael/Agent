<?php

namespace App\Http\Controllers;

use App\Models\ActivityLog;
use App\Models\TradingAnalysisDecision;
use App\Services\TradingService;
use Illuminate\Http\Request;

class TradingController extends Controller
{
    public function __construct(protected TradingService $trading)
    {
    }

    protected function logAction(Request $request, string $action, array $context = []): void
    {
        ActivityLog::create([
            'user_id' => $request->user()->id,
            'action' => $action,
            'entity_type' => 'trading',
            'entity_id' => null,
            'data' => $context,
            'ip_address' => $request->ip(),
            'user_agent' => $request->userAgent(),
            'description' => "Trading action: {$action}",
        ]);
    }

    public function status(Request $request)
    {
        try {
            return response()->json(['data' => $this->trading->status()]);
        } catch (\Exception $e) {
            return response()->json([
                'data' => [
                    'state' => 'stopped',
                    'mode' => 'not_configured',
                    'not_configured' => true,
                    'error' => config('app.debug') ? $e->getMessage() : null,
                ],
            ]);
        }
    }

    public function positions(Request $request)
    {
        try {
            return response()->json($this->trading->positions());
        } catch (\Exception $e) {
            return response()->json(['data' => []]);
        }
    }

    public function journal(Request $request)
    {
        $validated = $request->validate([
            'limit' => 'sometimes|integer|min:1|max:100',
            'offset' => 'sometimes|integer|min:0',
        ]);
        try {
            return response()->json(
                $this->trading->journal($validated['limit'] ?? 50, $validated['offset'] ?? 0)
            );
        } catch (\Exception $e) {
            return response()->json(['data' => []]);
        }
    }

    public function metrics(Request $request)
    {
        try {
            return response()->json($this->trading->metrics());
        } catch (\Exception $e) {
            return response()->json([
                'data' => [
                    'total_trades' => 0,
                    'win_rate' => 0,
                    'avg_rr' => 0,
                    'max_drawdown' => 0,
                    'sharpe_ratio' => 0,
                    'total_pnl' => 0,
                ],
            ]);
        }
    }

    public function pause(Request $request)
    {
        $result = $this->trading->pause();
        $this->logAction($request, 'trading.pause', $result);
        return response()->json($result);
    }

    public function resume(Request $request)
    {
        $result = $this->trading->resume();
        $this->logAction($request, 'trading.resume', $result);
        return response()->json($result);
    }

    public function kill(Request $request)
    {
        $result = $this->trading->kill();
        $this->logAction($request, 'trading.kill', $result);
        return response()->json($result);
    }

    public function start(Request $request)
    {
        try {
            $result = $this->trading->start();
            $this->logAction($request, 'trading.start', $result);
            return response()->json($result);
        } catch (\Exception $e) {
            return response()->json(['message' => $e->getMessage()], 502);
        }
    }

    public function preflightLatest(Request $request)
    {
        try {
            return response()->json($this->trading->getPreflightLatest());
        } catch (\Exception $e) {
            return response()->json(['data' => null, 'analysis_armed' => false]);
        }
    }

    public function runPreflight(Request $request)
    {
        try {
            $result = $this->trading->runPreflight();
            $this->logAction($request, 'trading.preflight', $result);
            return response()->json($result);
        } catch (\Exception $e) {
            return response()->json(['message' => $e->getMessage()], 502);
        }
    }

    public function analysisDecision(Request $request)
    {
        $latest = TradingAnalysisDecision::query()->latest()->first();
        if (!$latest) {
            return response()->json(['data' => null]);
        }
        return response()->json(['data' => $latest]);
    }

    public function analysisSources(Request $request)
    {
        try {
            return response()->json($this->trading->getAnalysisSources());
        } catch (\Exception $e) {
            return response()->json(['data' => []]);
        }
    }

    public function stop(Request $request)
    {
        $result = $this->trading->stop();
        $this->logAction($request, 'trading.stop', $result);
        return response()->json($result);
    }

    public function placeOrder(Request $request)
    {
        $validated = $request->validate([
            'symbol' => 'required|string',
            'direction' => 'required|in:buy,sell',
            'stake' => 'required|numeric|min:1',
            'stop_loss' => 'required|numeric|min:0.00001',
            'take_profit' => 'required|numeric|min:0.00001',
        ]);
        $result = $this->trading->placeOrder($validated);
        $this->logAction($request, 'trading.order', $validated);
        return response()->json($result);
    }

    public function closePosition(Request $request, int $contractId)
    {
        $result = $this->trading->closePosition($contractId);
        $this->logAction($request, 'trading.close_position', ['contract_id' => $contractId]);
        return response()->json($result);
    }

    public function closeAll(Request $request)
    {
        $result = $this->trading->closeAll();
        $this->logAction($request, 'trading.close_all', $result);
        return response()->json($result);
    }

    public function backtest(Request $request)
    {
        return response()->json($this->trading->backtest());
    }
}
