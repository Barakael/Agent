<?php

use App\Http\Controllers\AuthController;
use App\Http\Controllers\ActivityController;
use App\Http\Controllers\ConversationController;
use App\Http\Controllers\MessageController;
use App\Http\Controllers\MemoryController;
use App\Http\Controllers\NotificationController;
use App\Http\Controllers\PermissionController;
use App\Http\Controllers\SystemController;
use App\Http\Controllers\TradingController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;

/*
|--------------------------------------------------------------------------
| API Routes
|--------------------------------------------------------------------------
|
| Here is where you can register API routes for your application. These
| routes are loaded by the RouteServiceProvider within a group which
| is assigned the "api" middleware group. Enjoy building your API!
|
*/

// Public authentication routes
Route::middleware('throttle:auth-login')->group(function () {
    Route::post('/auth/register', [AuthController::class, 'register']);
    Route::post('/auth/login', [AuthController::class, 'login']);
});

// Protected routes (require authentication via Sanctum)
Route::middleware('auth:sanctum')->group(function () {
    // Auth endpoints
    Route::post('/auth/logout', [AuthController::class, 'logout']);
    Route::get('/auth/profile', [AuthController::class, 'profile']);
    Route::put('/auth/profile', [AuthController::class, 'updateProfile']);
    Route::post('/auth/change-password', [AuthController::class, 'changePassword']);

    // Conversation endpoints
    Route::get('/conversations', [ConversationController::class, 'index']);
    Route::post('/conversations', [ConversationController::class, 'store']);
    Route::get('/conversations/{conversation}', [ConversationController::class, 'show']);
    Route::put('/conversations/{conversation}', [ConversationController::class, 'update']);
    Route::delete('/conversations/{conversation}', [ConversationController::class, 'destroy']);
    Route::post('/conversations/{conversation}/archive', [ConversationController::class, 'archive']);

    // Message endpoints
    Route::get('/conversations/{conversation}/messages', [MessageController::class, 'index']);
    Route::post('/conversations/{conversation}/messages', [MessageController::class, 'store'])->middleware('throttle:high-cost-ai');
    Route::delete('/conversations/{conversation}/messages/{message}', [MessageController::class, 'destroy']);

    // Task and execution endpoints
    Route::get('/tasks', [TaskController::class, 'index']);
    Route::post('/tasks', [TaskController::class, 'store']);
    Route::get('/tasks/{task}', [TaskController::class, 'show']);
    Route::get('/tasks/{task}/logs', [TaskController::class, 'logs']);
    Route::put('/tasks/{task}', [TaskController::class, 'update']);
    Route::post('/tasks/{task}/retry', [TaskController::class, 'retry']);
    Route::post('/tasks/{task}/tools/execute', [TaskController::class, 'executeTool']);

    // Activity and memory endpoints
    Route::get('/activity-logs', [ActivityController::class, 'index']);
    Route::get('/memories', [MemoryController::class, 'index']);
    Route::post('/memories', [MemoryController::class, 'store']);
    Route::put('/memories/{memory}', [MemoryController::class, 'update']);
    Route::delete('/memories/{memory}', [MemoryController::class, 'destroy']);

    // Notification endpoints
    Route::get('/notifications', [NotificationController::class, 'index']);
    Route::post('/notifications', [NotificationController::class, 'store']);
    Route::post('/notifications/read-all', [NotificationController::class, 'markAllRead']);
    Route::post('/notifications/{notification}/read', [NotificationController::class, 'markRead']);

    // Permission and approvals (write actions require admin role)
    Route::get('/permissions', [PermissionController::class, 'index']);
    Route::post('/permissions/approvals', [PermissionController::class, 'createApproval']);
    Route::get('/permissions/approvals', [PermissionController::class, 'listApprovals']);
    Route::post('/permissions/approvals/{approvalRequest}/decision', [PermissionController::class, 'decideApproval'])->middleware('role:admin');
    Route::post('/permissions', [PermissionController::class, 'store'])->middleware('role:admin');
    Route::put('/permissions/{permission}', [PermissionController::class, 'update'])->middleware('role:admin');
    Route::delete('/permissions/{permission}', [PermissionController::class, 'destroy'])->middleware('role:admin');

    // System status
    Route::get('/system/health', [SystemController::class, 'health']);

    // Trading endpoints (proxied to trading-engine)
    Route::prefix('trading')->group(function () {
        Route::get('/status', [TradingController::class, 'status']);
        Route::get('/positions', [TradingController::class, 'positions']);
        Route::get('/journal', [TradingController::class, 'journal']);
        Route::get('/metrics', [TradingController::class, 'metrics']);
        Route::post('/pause', [TradingController::class, 'pause']);
        Route::post('/resume', [TradingController::class, 'resume']);
        Route::post('/kill', [TradingController::class, 'kill'])->middleware('role:admin');
        Route::post('/start', [TradingController::class, 'start']);
        Route::post('/stop', [TradingController::class, 'stop']);
        Route::post('/orders', [TradingController::class, 'placeOrder']);
        Route::post('/positions/close-all', [TradingController::class, 'closeAll']);
        Route::post('/positions/{contractId}/close', [TradingController::class, 'closePosition']);
        Route::post('/backtest', [TradingController::class, 'backtest'])->middleware('role:admin');
    });

    // User endpoint
    Route::get('/user', function (Request $request) {
        return $request->user();
    });
});
