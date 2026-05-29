<?php

namespace App\Http\Controllers;

use App\Models\AiMemory;
use Illuminate\Http\Request;

class MemoryController extends Controller
{
    public function index(Request $request)
    {
        $query = $request->user()->memories()->orderByDesc('importance')->orderByDesc('updated_at');

        if ($memoryType = $request->query('memory_type')) {
            $query->where('memory_type', $memoryType);
        }

        $memories = $query->paginate(50);

        return response()->json([
            'data' => $memories->items(),
            'pagination' => [
                'current_page' => $memories->currentPage(),
                'total' => $memories->total(),
                'per_page' => $memories->perPage(),
                'last_page' => $memories->lastPage(),
            ],
        ]);
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'memory_type' => 'required|in:preference,workflow,context,tooling',
            'key' => 'required|string|max:255',
            'value' => 'required|string',
            'importance' => 'nullable|numeric|min:0|max:1',
        ]);

        $memory = $request->user()->memories()->create([
            ...$validated,
            'importance' => $validated['importance'] ?? 0.5,
            'last_used_at' => now(),
        ]);

        return response()->json([
            'message' => 'Memory saved successfully',
            'data' => $memory,
        ], 201);
    }

    public function update(Request $request, AiMemory $memory)
    {
        if ($memory->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        $validated = $request->validate([
            'value' => 'sometimes|string',
            'importance' => 'sometimes|numeric|min:0|max:1',
            'last_used_at' => 'sometimes|date',
        ]);

        $memory->update($validated);

        return response()->json([
            'message' => 'Memory updated successfully',
            'data' => $memory->fresh(),
        ]);
    }

    public function destroy(Request $request, AiMemory $memory)
    {
        if ($memory->user_id !== $request->user()->id) {
            return response()->json(['message' => 'Unauthorized'], 403);
        }

        $memory->delete();

        return response()->json([
            'message' => 'Memory deleted successfully',
        ]);
    }
}
