<?php

namespace App\Http\Controllers;

use App\Models\Conversation;
use Illuminate\Http\Request;

class ConversationController extends Controller
{
    /**
     * Get all conversations for the authenticated user.
     */
    public function index(Request $request)
    {
        $conversations = $request->user()
            ->conversations()
            ->with('latestMessage')
            ->orderBy('updated_at', 'desc')
            ->paginate(20);

        return response()->json([
            'data' => $conversations->items(),
            'pagination' => [
                'current_page' => $conversations->currentPage(),
                'total' => $conversations->total(),
                'per_page' => $conversations->perPage(),
                'last_page' => $conversations->lastPage(),
            ],
        ]);
    }

    /**
     * Create a new conversation.
     */
    public function store(Request $request)
    {
        $validated = $request->validate([
            'title' => 'sometimes|string|max:255',
            'description' => 'sometimes|string',
        ]);

        $conversation = $request->user()->conversations()->create($validated + [
            'status' => 'active',
        ]);

        return response()->json([
            'message' => 'Conversation created successfully',
            'data' => $conversation,
        ], 201);
    }

    /**
     * Get a specific conversation with its messages.
     */
    public function show(Request $request, Conversation $conversation)
    {
        // Check authorization
        if ($conversation->user_id !== $request->user()->id) {
            return response()->json([
                'message' => 'Unauthorized',
            ], 403);
        }

        $messages = $conversation->messages()->paginate(50);

        return response()->json([
            'data' => [
                'conversation' => $conversation,
                'messages' => $messages->items(),
                'pagination' => [
                    'current_page' => $messages->currentPage(),
                    'total' => $messages->total(),
                    'per_page' => $messages->perPage(),
                    'last_page' => $messages->lastPage(),
                ],
            ],
        ]);
    }

    /**
     * Update a conversation.
     */
    public function update(Request $request, Conversation $conversation)
    {
        // Check authorization
        if ($conversation->user_id !== $request->user()->id) {
            return response()->json([
                'message' => 'Unauthorized',
            ], 403);
        }

        $validated = $request->validate([
            'title' => 'sometimes|string|max:255',
            'description' => 'sometimes|string',
            'status' => 'sometimes|in:active,archived,deleted',
        ]);

        $conversation->update($validated);

        return response()->json([
            'message' => 'Conversation updated successfully',
            'data' => $conversation,
        ]);
    }

    /**
     * Delete a conversation.
     */
    public function destroy(Request $request, Conversation $conversation)
    {
        // Check authorization
        if ($conversation->user_id !== $request->user()->id) {
            return response()->json([
                'message' => 'Unauthorized',
            ], 403);
        }

        $conversation->delete();

        return response()->json([
            'message' => 'Conversation deleted successfully',
        ]);
    }

    /**
     * Archive a conversation.
     */
    public function archive(Request $request, Conversation $conversation)
    {
        // Check authorization
        if ($conversation->user_id !== $request->user()->id) {
            return response()->json([
                'message' => 'Unauthorized',
            ], 403);
        }

        $conversation->update(['status' => 'archived']);

        return response()->json([
            'message' => 'Conversation archived successfully',
            'data' => $conversation,
        ]);
    }
}
