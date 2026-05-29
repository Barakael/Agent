<?php

namespace App\Jobs;

use App\Models\AiTask;
use App\Models\TaskLog;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class ExecuteAiTaskJob implements ShouldQueue
{
    use Queueable;

    public function __construct(public int $taskId)
    {
    }

    public function handle(): void
    {
        $task = AiTask::query()->find($this->taskId);
        if ($task === null) {
            return;
        }

        $task->update([
            'status' => 'running',
            'started_at' => now(),
        ]);

        TaskLog::create([
            'task_id' => $task->id,
            'user_id' => $task->user_id,
            'event' => 'task_started',
            'message' => 'Task execution started by queue worker.',
        ]);

        try {
            $response = Http::withHeaders([
                'Authorization' => 'Bearer '.config('services.ai.api_key'),
                'Accept' => 'application/json',
            ])->timeout((int) config('services.ai.timeout', 30))
                ->post(rtrim((string) config('services.ai.url'), '/').'/tasks/execute', [
                    'task_id' => (string) $task->id,
                    'goal' => $task->goal ?: $task->title,
                    'context' => [
                        'priority' => $task->priority,
                        'metadata' => $task->metadata,
                    ],
                ]);

            if (!$response->successful()) {
                throw new \RuntimeException('AI task execution failed with status '.$response->status());
            }

            $data = $response->json();

            $task->update([
                'status' => 'completed',
                'completed_at' => now(),
                'metadata' => array_merge((array) $task->metadata, [
                    'trace_id' => $data['trace_id'] ?? null,
                    'summary' => $data['summary'] ?? null,
                ]),
            ]);

            TaskLog::create([
                'task_id' => $task->id,
                'user_id' => $task->user_id,
                'event' => 'task_completed',
                'message' => 'Task execution completed successfully.',
                'context' => [
                    'trace_id' => $data['trace_id'] ?? null,
                ],
            ]);
        } catch (\Throwable $exception) {
            Log::error('Queued AI task failed', [
                'task_id' => $task->id,
                'error' => $exception->getMessage(),
            ]);

            $task->update([
                'status' => 'failed',
                'completed_at' => now(),
            ]);

            TaskLog::create([
                'task_id' => $task->id,
                'user_id' => $task->user_id,
                'event' => 'task_failed',
                'level' => 'error',
                'message' => $exception->getMessage(),
            ]);
        }
    }
}
