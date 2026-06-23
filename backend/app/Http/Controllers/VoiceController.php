<?php

namespace App\Http\Controllers;

use App\Services\AIService;
use Illuminate\Http\Request;

class VoiceController extends Controller
{
    public function transcribe(Request $request, AIService $aiService)
    {
        $request->validate([
            'audio' => 'required|file|max:10240',
        ]);

        $text = $aiService->transcribeAudio($request->file('audio'));

        return response()->json([
            'data' => ['text' => $text],
        ]);
    }

    public function speak(Request $request, AIService $aiService)
    {
        $validated = $request->validate([
            'text' => 'required|string|max:4096',
        ]);

        $audio = $aiService->speakText($validated['text']);

        return response($audio, 200, [
            'Content-Type' => 'audio/mpeg',
        ]);
    }
}
