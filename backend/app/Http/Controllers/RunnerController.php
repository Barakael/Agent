<?php

namespace App\Http\Controllers;

use App\Services\AIService;
use Illuminate\Http\Request;

class RunnerController extends Controller
{
    public function status(Request $request, AIService $aiService)
    {
        return response()->json([
            'data' => $aiService->runnerStatus(),
        ]);
    }
}
