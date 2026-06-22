<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class TradingService
{
    protected string $tradingUrl;
    protected string $apiKey;
    protected int $timeout;

    public function __construct()
    {
        $this->tradingUrl = rtrim(config('services.trading.url', 'http://localhost:8002'), '/');
        $this->apiKey = config('services.trading.api_key', '');
        $this->timeout = config('services.trading.timeout', 30);
    }

    protected function getHeaders(): array
    {
        $headers = [
            'Content-Type' => 'application/json',
            'Accept' => 'application/json',
        ];
        if (!empty($this->apiKey)) {
            $headers['Authorization'] = "Bearer {$this->apiKey}";
        }
        return $headers;
    }

    protected function request(string $method, string $path, array $body = []): array
    {
        $http = Http::withHeaders($this->getHeaders())->timeout($this->timeout);
        $url = "{$this->tradingUrl}{$path}";

        $response = match (strtoupper($method)) {
            'GET' => $http->get($url, $body),
            'POST' => $http->post($url, $body),
            default => throw new \InvalidArgumentException("Unsupported method {$method}"),
        };

        if (!$response->successful()) {
            Log::error('Trading Service Error', [
                'status' => $response->status(),
                'body' => $response->body(),
                'path' => $path,
            ]);
            throw new \Exception("Trading service returned status {$response->status()}");
        }

        return $response->json() ?? [];
    }

    public function healthCheck(): bool
    {
        try {
            $this->request('GET', '/health');
            return true;
        } catch (\Exception $e) {
            Log::warning('Trading service health check failed', ['error' => $e->getMessage()]);
            return false;
        }
    }

    public function status(): array
    {
        return $this->request('GET', '/status');
    }

    public function positions(): array
    {
        return $this->request('GET', '/positions');
    }

    public function journal(int $limit = 50, int $offset = 0): array
    {
        return $this->request('GET', '/journal', ['limit' => $limit, 'offset' => $offset]);
    }

    public function metrics(): array
    {
        return $this->request('GET', '/metrics');
    }

    public function pause(): array
    {
        return $this->request('POST', '/pause');
    }

    public function resume(): array
    {
        return $this->request('POST', '/resume');
    }

    public function kill(): array
    {
        return $this->request('POST', '/kill');
    }

    public function start(): array
    {
        return $this->request('POST', '/start');
    }

    public function stop(): array
    {
        return $this->request('POST', '/stop');
    }

    public function placeOrder(array $order): array
    {
        return $this->request('POST', '/orders', $order);
    }

    public function closePosition(int $contractId): array
    {
        return $this->request('POST', "/positions/{$contractId}/close");
    }

    public function closeAll(): array
    {
        return $this->request('POST', '/positions/close-all');
    }

    public function backtest(): array
    {
        return $this->request('POST', '/backtest');
    }

    public function runPreflight(): array
    {
        return $this->request('POST', '/preflight');
    }

    public function getPreflightLatest(): array
    {
        return $this->request('GET', '/preflight/latest');
    }

    public function getAnalysisSources(): array
    {
        return $this->request('GET', '/analysis/sources');
    }

    public function pushAiDecision(array $decision): array
    {
        return $this->request('POST', '/analysis/ai-decision', $decision);
    }
}
