<?php

namespace App\Http\Controllers;

use App\Jobs\ExecuteAiTaskJob;
use App\Models\AiTask;
use App\Models\ApprovalRequest;
use App\Models\Permission;
use App\Models\TaskLog;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;

class TaskController extends Controller
{
    public function index(Request $request)
    {
        $query = $request->user()->tasks()->with('logs');

        if ($status = $request->query('status')) {
            $query->where('status', $status);
        }

        $tasks = $query->orderByDesc('created_at')->paginate(25);

        return response()->json([
            'data' => $tasks->items(),
            'pagination' => [
                'current_page' => $tasks->currentPage(),
                'total' => $tasks->total(),
                'per_page' => $tasks->perPage(),
                'last_page' => $tasks->lastPage(),
            ],
        ]);
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'title' => 'required|string|max:255',
            'goal' => 'nullable|string',
            'priority' => 'nullable|in:low,medium,high',
            'metadata' => 'nullable|array',
        ]);

        $task = $request->user()->tasks()->create([
            'title' => $validated['title'],
            'goal' => $validated['goal'] ?? null,
            'priority' => $validated['priority'] ?? 'medium',
            'metadata' => $validated['metadata'] ?? null,
            'status' => 'pending',
        ]);

        TaskLog::create([
            'task_id' => $task->id,
            'user_id' => $request->user()->id,
            'event' => 'task_created',
            'message' => 'Task created and queued for execution.',
            'level' => 'info',
        ]);

        ExecuteAiTaskJob::dispatch($task->id);

        return response()->json([
            'message' => 'Task created successfully',
            'data' => $task->load('logs'),
        ], 201);
    }

    public function show(Request $request, AiTask $task)
    {
        if ($task->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        return response()->json([
            'data' => $task->load('logs'),
        ]);
    }

    public function update(Request $request, AiTask $task)
    {
        if ($task->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        $validated = $request->validate([
            'status' => 'sometimes|in:pending,running,completed,failed,cancelled',
            'priority' => 'sometimes|in:low,medium,high',
            'metadata' => 'sometimes|array',
        ]);

        $task->update($validated);

        if (($validated['status'] ?? null) === 'running' && $task->started_at === null) {
            $task->update(['started_at' => now()]);
        }

        if (in_array($validated['status'] ?? '', ['completed', 'failed', 'cancelled'], true)) {
            $task->update(['completed_at' => now()]);
        }

        TaskLog::create([
            'task_id' => $task->id,
            'user_id' => $request->user()->id,
            'event' => 'task_updated',
            'message' => 'Task state updated.',
            'level' => 'info',
            'context' => $validated,
        ]);

        return response()->json([
            'message' => 'Task updated successfully',
            'data' => $task->fresh()->load('logs'),
        ]);
    }

    public function logs(Request $request, AiTask $task)
    {
        if ($task->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        $logs = $task->logs()->paginate(100);

        return response()->json([
            'data' => $logs->items(),
            'pagination' => [
                'current_page' => $logs->currentPage(),
                'total' => $logs->total(),
                'per_page' => $logs->perPage(),
                'last_page' => $logs->lastPage(),
            ],
        ]);
    }

    public function retry(Request $request, AiTask $task)
    {
        if ($task->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        $task->update([
            'status' => 'pending',
            'completed_at' => null,
        ]);

        TaskLog::create([
            'task_id' => $task->id,
            'user_id' => $request->user()->id,
            'event' => 'task_retried',
            'message' => 'Task was re-queued by the user.',
            'level' => 'warning',
        ]);

        ExecuteAiTaskJob::dispatch($task->id);

        return response()->json([
            'message' => 'Task re-queued successfully',
            'data' => $task->fresh()->load('logs'),
        ]);
    }

    public function executeTool(Request $request, AiTask $task)
    {
        if ($task->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        $validated = $request->validate([
            'tool' => 'required|string|max:80',
            'action' => 'required|string|max:80',
            'payload' => 'nullable|array',
            'approval_request_id' => 'required|exists:approval_requests,id',
        ]);

        $actionKey = $validated['tool'].'.'.$validated['action'];
        $policy = Permission::query()
            ->where('scope', 'tool')
            ->where('resource', $actionKey)
            ->first();

        if ($policy && $policy->access === 'deny') {
            return response()->json(['message' => 'This tool action is blocked by policy.'], 403);
        }

        $approval = ApprovalRequest::query()->findOrFail($validated['approval_request_id']);
        if ($approval->status !== 'approved') {
            return response()->json(['message' => 'Tool action requires an approved request.'], 403);
        }

        $response = Http::withHeaders([
            'Authorization' => 'Bearer '.config('services.ai.api_key'),
            'X-Approval-Token' => config('services.ai.tool_approval_token'),
            'Accept' => 'application/json',
        ])->timeout((int) config('services.ai.timeout', 30))
            ->post(rtrim((string) config('services.ai.url'), '/').'/tools/execute', [
                'task_id' => (string) $task->id,
                'tool' => $validated['tool'],
                'action' => $validated['action'],
                'payload' => $validated['payload'] ?? [],
            ]);

        if (!$response->successful()) {
            return response()->json([
                'message' => 'Tool execution failed',
                'error' => $response->json('detail', 'Tool endpoint returned an error'),
            ], 502);
        }

        $data = $response->json();
        TaskLog::create([
            'task_id' => $task->id,
            'user_id' => $request->user()->id,
            'event' => 'tool_executed',
            'message' => "Tool action {$actionKey} executed.",
            'context' => [
                'trace_id' => $data['trace_id'] ?? null,
            ],
        ]);

        return response()->json([
            'message' => 'Tool execution accepted',
            'data' => $data,
        ]);
    }
}
