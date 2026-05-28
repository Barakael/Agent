<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class AIService
{
    protected string $aiServiceUrl;
    protected string $apiKey;
    protected int $timeout;

    public function __construct()
    {
        $this->aiServiceUrl = rtrim(config('services.ai.url', 'http://localhost:8000'), '/');
        $this->apiKey = config('services.ai.api_key', '');
        $this->timeout = config('services.ai.timeout', 30);
    }

    /**
     * Send a chat request to the AI service.
     *
     * @param array $conversationHistory Array of messages with 'role' and 'content' keys
     * @param array $options Additional options for the AI request
     * @return string The AI response
     * @throws \Exception
     */
    public function chat(array $conversationHistory, array $options = []): string
    {
        try {
            $payload = array_merge([
                'messages' => $conversationHistory,
            ], $options);

            $response = Http::withHeaders($this->getHeaders())
                ->timeout($this->timeout)
                ->post("{$this->aiServiceUrl}/api/chat", $payload);

            if (!$response->successful()) {
                Log::error('AI Service Error', [
                    'status' => $response->status(),
                    'body' => $response->body(),
                ]);

                throw new \Exception("AI Service returned status {$response->status()}");
            }

            $data = $response->json();

            if (!isset($data['response'])) {
                throw new \Exception("Invalid AI Service response format");
            }

            return $data['response'];
        } catch (\Exception $e) {
            Log::error('AI Service Exception', [
                'message' => $e->getMessage(),
                'trace' => $e->getTraceAsString(),
            ]);

            throw $e;
        }
    }

    /**
     * Get the headers for API requests.
     */
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

    /**
     * Health check for the AI service.
     */
    public function healthCheck(): bool
    {
        try {
            $response = Http::timeout(5)
                ->get("{$this->aiServiceUrl}/health");

            return $response->successful();
        } catch (\Exception $e) {
            Log::warning('AI Service health check failed', [
                'error' => $e->getMessage(),
            ]);

            return false;
        }
    }
}
