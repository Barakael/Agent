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
     * Send a chat request to the AI agent with computer tool access.
     *
     * @return array{response: string, model?: string, tokens_used?: array, tool_actions?: array, metadata?: array}
     * @throws \Exception
     */
    public function agentChat(array $conversationHistory, array $options = []): array
    {
        try {
            $payload = array_merge([
                'messages' => $conversationHistory,
            ], $options);

            $headers = $this->getHeaders();
            $approvalToken = config('services.ai.tool_approval_token', '');
            if (!empty($approvalToken)) {
                $headers['X-Approval-Token'] = $approvalToken;
            }

            $response = Http::withHeaders($headers)
                ->timeout($this->timeout)
                ->post("{$this->aiServiceUrl}/chat/agent", $payload);

            if (!$response->successful()) {
                Log::error('AI Agent Service Error', [
                    'status' => $response->status(),
                    'body' => $response->body(),
                ]);

                throw new \Exception("AI Agent Service returned status {$response->status()}");
            }

            $data = $response->json();

            if (!isset($data['response'])) {
                throw new \Exception('Invalid AI Agent Service response format');
            }

            return $data;
        } catch (\Exception $e) {
            Log::error('AI Agent Service Exception', [
                'message' => $e->getMessage(),
                'trace' => $e->getTraceAsString(),
            ]);

            throw $e;
        }
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
                ->post("{$this->aiServiceUrl}/chat", $payload);

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
            $response = Http::withHeaders($this->getHeaders())
                ->timeout(5)
                ->get("{$this->aiServiceUrl}/health");

            return $response->successful();
        } catch (\Exception $e) {
            Log::warning('AI Service health check failed', [
                'error' => $e->getMessage(),
            ]);

            return false;
        }
    }

    /**
     * Transcribe uploaded audio via ai-agent Whisper endpoint.
     *
     * @return string transcribed text
     */
    public function transcribeAudio(\Illuminate\Http\UploadedFile $file): string
    {
        $headers = ['Accept' => 'application/json'];
        if (!empty($this->apiKey)) {
            $headers['Authorization'] = "Bearer {$this->apiKey}";
        }

        $response = Http::withHeaders($headers)
            ->timeout(60)
            ->attach('audio', fopen($file->getRealPath(), 'r'), $file->getClientOriginalName())
            ->post("{$this->aiServiceUrl}/voice/transcribe");

        if (!$response->successful()) {
            Log::error('Voice transcribe failed', [
                'status' => $response->status(),
                'body' => $response->body(),
            ]);
            throw new \Exception('Voice transcription failed');
        }

        $data = $response->json();
        $text = $data['text'] ?? $data['data']['text'] ?? null;
        if (!is_string($text) || $text === '') {
            throw new \Exception('Invalid transcription response');
        }

        return $text;
    }

    /**
     * Synthesize speech audio bytes from text.
     */
    public function speakText(string $text): string
    {
        $response = Http::withHeaders($this->getHeaders())
            ->timeout(60)
            ->post("{$this->aiServiceUrl}/voice/speak", [
                'text' => $text,
            ]);

        if (!$response->successful()) {
            Log::error('Voice speak failed', [
                'status' => $response->status(),
                'body' => $response->body(),
            ]);
            throw new \Exception('Speech synthesis failed');
        }

        return $response->body();
    }

    /**
     * Local runner reachability from ai-agent.
     *
     * @return array{runner_enabled: bool, online: bool, platform: ?string}
     */
    public function runnerStatus(): array
    {
        try {
            $response = Http::withHeaders($this->getHeaders())
                ->timeout(10)
                ->get("{$this->aiServiceUrl}/runner/status");

            if (!$response->successful()) {
                return [
                    'runner_enabled' => false,
                    'online' => false,
                    'platform' => null,
                ];
            }

            return $response->json();
        } catch (\Exception $e) {
            Log::warning('Runner status check failed', ['error' => $e->getMessage()]);

            return [
                'runner_enabled' => false,
                'online' => false,
                'platform' => null,
            ];
        }
    }
}
