<?php

namespace App\Http\Controllers;

use App\Models\AiTask;
use App\Models\ApprovalRequest;
use App\Models\UserNotification;
use App\Services\AIService;
use Illuminate\Http\Request;

class SystemController extends Controller
{
    public function health(Request $request, AIService $aiService)
    {
        $user = $request->user();
        $userTaskQuery = AiTask::query()->where('user_id', $user->id);

        return response()->json([
            'data' => [
                'services' => [
                    'backend' => [
                        'status' => 'ok',
                        'timestamp' => now()->toIso8601String(),
                    ],
                    'ai_service' => [
                        'status' => $aiService->healthCheck() ? 'ok' : 'degraded',
                    ],
                    'queue' => [
                        'status' => 'ok',
                        'pending_tasks' => $userTaskQuery->where('status', 'pending')->count(),
                        'running_tasks' => AiTask::query()->where('user_id', $user->id)->where('status', 'running')->count(),
                    ],
                    'realtime' => [
                        'status' => 'configured',
                        'transport' => config('services.realtime.transport', 'websocket'),
                    ],
                ],
                'counts' => [
                    'unread_notifications' => UserNotification::query()
                        ->where('user_id', $user->id)
                        ->whereNull('read_at')
                        ->count(),
                    'pending_approvals' => ApprovalRequest::query()
                        ->when($user->role !== 'admin', fn ($q) => $q->where('user_id', $user->id))
                        ->where('status', 'pending')
                        ->count(),
                ],
            ],
        ]);
    }
}
