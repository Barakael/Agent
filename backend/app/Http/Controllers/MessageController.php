<?php

namespace App\Http\Controllers;

use App\Models\Conversation;
use App\Models\Message;
use App\Models\UserNotification;
use App\Services\AIService;
use Illuminate\Http\Request;

class MessageController extends Controller
{
    protected AIService $aiService;

    public function __construct(AIService $aiService)
    {
        $this->aiService = $aiService;
    }

    /**
     * Get all messages in a conversation.
     */
    public function index(Request $request, Conversation $conversation)
    {
        // Check authorization
        if ($conversation->user_id !== $request->user()->id) {
            return response()->json([
                'message' => 'Unauthorized',
            ], 403);
        }

        $messages = $conversation->messages()->paginate(50);

        return response()->json([
            'data' => $messages->items(),
            'pagination' => [
                'current_page' => $messages->currentPage(),
                'total' => $messages->total(),
                'per_page' => $messages->perPage(),
                'last_page' => $messages->lastPage(),
            ],
        ]);
    }

    /**
     * Send a message and get AI response.
     */
    public function store(Request $request, Conversation $conversation)
    {
        // Check authorization
        if ($conversation->user_id !== $request->user()->id) {
            return response()->json([
                'message' => 'Unauthorized',
            ], 403);
        }

        $validated = $request->validate([
            'content' => 'required|string',
        ]);

        // Store user message
        $userMessage = $conversation->messages()->create([
            'user_id' => $request->user()->id,
            'role' => 'user',
            'content' => $validated['content'],
            'status' => 'completed',
        ]);

        // Get conversation history for context
        $conversationHistory = $conversation->messages()
            ->where('status', 'completed')
            ->orderBy('created_at', 'asc')
            ->get()
            ->map(fn($msg) => [
                'role' => $msg->role,
                'content' => $msg->content,
            ])
            ->toArray();

        // Get AI response
        try {
            $aiResponse = $this->aiService->chat($conversationHistory);

            // Store assistant message
            $assistantMessage = $conversation->messages()->create([
                'user_id' => $request->user()->id,
                'role' => 'assistant',
                'content' => $aiResponse,
                'status' => 'completed',
                'metadata' => [
                    'source' => 'openai',
                    'status' => 'completed',
                ],
            ]);

            try {
                UserNotification::create([
                    'user_id' => $request->user()->id,
                    'type' => 'chat',
                    'title' => 'AI response received',
                    'body' => 'A new assistant response is ready in your conversation.',
                    'data' => [
                        'conversation_id' => $conversation->id,
                        'message_id' => $assistantMessage->id,
                    ],
                ]);
            } catch (\Throwable $notificationError) {
                \Log::warning('Failed to create chat notification', [
                    'error' => $notificationError->getMessage(),
                    'conversation_id' => $conversation->id,
                ]);
            }

            // Update conversation metadata
            $conversation->update([
                'message_count' => $conversation->messages()->count(),
                'last_message_at' => now(),
            ]);

            return response()->json([
                'message' => 'Message sent successfully',
                'data' => [
                    'user_message' => $userMessage,
                    'assistant_message' => $assistantMessage,
                ],
            ], 201);
        } catch (\Exception $e) {
            // Log the error
            \Log::error('AI Service Error', [
                'error' => $e->getMessage(),
                'conversation_id' => $conversation->id,
            ]);

            // Mark message as failed
            $userMessage->update(['status' => 'failed']);

            return response()->json([
                'message' => 'Failed to get AI response',
                'error' => config('app.debug') ? $e->getMessage() : 'An error occurred',
            ], 500);
        }
    }

    /**
     * Delete a message.
     */
    public function destroy(Request $request, Conversation $conversation, Message $message)
    {
        // Check authorization
        if ($conversation->user_id !== $request->user()->id || $message->conversation_id !== $conversation->id) {
            return response()->json([
                'message' => 'Unauthorized',
            ], 403);
        }

        $message->delete();

        return response()->json([
            'message' => 'Message deleted successfully',
        ]);
    }
}
