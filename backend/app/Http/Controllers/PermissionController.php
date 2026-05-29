<?php

namespace App\Http\Controllers;

use App\Models\ApprovalRequest;
use App\Models\Permission;
use Illuminate\Http\Request;

class PermissionController extends Controller
{
    public function index()
    {
        return response()->json([
            'data' => Permission::query()->orderBy('scope')->orderBy('resource')->get(),
        ]);
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'scope' => 'required|in:domain,folder,tool',
            'resource' => 'required|string|max:255',
            'access' => 'required|in:allow,deny',
            'requires_confirmation' => 'sometimes|boolean',
        ]);

        $permission = Permission::query()->updateOrCreate(
            ['scope' => $validated['scope'], 'resource' => $validated['resource']],
            [
                'access' => $validated['access'],
                'requires_confirmation' => $validated['requires_confirmation'] ?? true,
                'created_by' => $request->user()->id,
            ],
        );

        return response()->json([
            'message' => 'Permission policy saved',
            'data' => $permission,
        ], 201);
    }

    public function update(Request $request, Permission $permission)
    {
        $validated = $request->validate([
            'access' => 'sometimes|in:allow,deny',
            'requires_confirmation' => 'sometimes|boolean',
        ]);

        $permission->update($validated);

        return response()->json([
            'message' => 'Permission policy updated',
            'data' => $permission->fresh(),
        ]);
    }

    public function destroy(Permission $permission)
    {
        $permission->delete();

        return response()->json([
            'message' => 'Permission policy removed',
        ]);
    }

    public function listApprovals(Request $request)
    {
        $query = ApprovalRequest::query()->with(['user', 'reviewer'])->orderByDesc('created_at');

        if ($request->user()->role !== 'admin') {
            $query->where('user_id', $request->user()->id);
        }

        if ($status = $request->query('status')) {
            $query->where('status', $status);
        }

        $items = $query->paginate(50);

        return response()->json([
            'data' => $items->items(),
            'pagination' => [
                'current_page' => $items->currentPage(),
                'total' => $items->total(),
                'per_page' => $items->perPage(),
                'last_page' => $items->lastPage(),
            ],
        ]);
    }

    public function createApproval(Request $request)
    {
        $validated = $request->validate([
            'task_id' => 'nullable|exists:ai_tasks,id',
            'action_type' => 'required|string|max:80',
            'target' => 'required|string',
            'payload' => 'nullable|array',
        ]);

        $approval = ApprovalRequest::create([
            ...$validated,
            'user_id' => $request->user()->id,
            'status' => 'pending',
        ]);

        return response()->json([
            'message' => 'Approval request created',
            'data' => $approval,
        ], 201);
    }

    public function decideApproval(Request $request, ApprovalRequest $approvalRequest)
    {
        $validated = $request->validate([
            'decision' => 'required|in:approved,rejected',
            'reason' => 'nullable|string',
        ]);

        $approvalRequest->update([
            'status' => $validated['decision'],
            'decision_reason' => $validated['reason'] ?? null,
            'reviewed_by' => $request->user()->id,
            'reviewed_at' => now(),
        ]);

        return response()->json([
            'message' => 'Approval decision recorded',
            'data' => $approvalRequest->fresh(),
        ]);
    }
}
