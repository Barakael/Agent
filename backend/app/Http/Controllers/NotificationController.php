<?php

namespace App\Http\Controllers;

use App\Models\UserNotification;
use Illuminate\Http\Request;

class NotificationController extends Controller
{
    public function index(Request $request)
    {
        $query = $request->user()->notifications()->orderByDesc('created_at');

        if (($request->query('unread') ?? 'false') === 'true') {
            $query->whereNull('read_at');
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

    public function store(Request $request)
    {
        $validated = $request->validate([
            'type' => 'required|string|max:80',
            'title' => 'required|string|max:255',
            'body' => 'nullable|string',
            'data' => 'nullable|array',
        ]);

        $notification = UserNotification::create([
            ...$validated,
            'user_id' => $request->user()->id,
        ]);

        return response()->json([
            'message' => 'Notification created',
            'data' => $notification,
        ], 201);
    }

    public function markRead(Request $request, UserNotification $notification)
    {
        if ($notification->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        $notification->update(['read_at' => now()]);

        return response()->json([
            'message' => 'Notification marked as read',
            'data' => $notification->fresh(),
        ]);
    }

    public function markAllRead(Request $request)
    {
        $request->user()->notifications()->whereNull('read_at')->update(['read_at' => now()]);

        return response()->json([
            'message' => 'All notifications marked as read',
        ]);
    }
}
