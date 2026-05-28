<?php

namespace App\Http\Middleware;

use App\Models\ActivityLog;
use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;
use Symfony\Component\HttpFoundation\Response;

class LogActivity
{
    /**
     * Handle an incoming request.
     */
    public function handle(Request $request, Closure $next): Response
    {
        $key = 'api-rate:' . ($request->user()?->id ?? $request->ip());
        $limit = 60;
        $period = 60; // seconds

        if (!Cache::has($key)) {
            Cache::put($key, 0, $period);
        }

        $count = Cache::increment($key);
        if ($count === false) {
            Cache::put($key, 1, $period);
            $count = 1;
        }

        if ($count > $limit) {
            return response()->json([
                'message' => 'Too many requests. Please wait a moment and try again.',
                'retry_after' => $period,
            ], 429);
        }

        $response = $next($request);

        try {
            ActivityLog::create([
                'user_id' => $request->user()?->id,
                'action' => Str::upper($request->method()),
                'entity_type' => $this->resolveEntityType($request),
                'entity_id' => $this->resolveEntityId($request),
                'method' => $request->method(),
                'endpoint' => $request->path(),
                'ip_address' => $request->ip(),
                'user_agent' => $request->userAgent(),
                'status_code' => $response->getStatusCode(),
                'description' => $response->getStatusCode() >= 400 ? 'API request returned an error' : 'API request completed successfully',
                'data' => [
                    'query' => $request->query(),
                    'body' => $this->normalizeBody($request->all()),
                ],
            ]);
        } catch (\Throwable $e) {
            Log::warning('Failed to write activity log', [
                'error' => $e->getMessage(),
                'request' => $request->path(),
            ]);
        }

        return $response;
    }

    protected function normalizeBody(array $body): array
    {
        if (count($body) > 25) {
            return array_slice($body, 0, 25);
        }

        return $body;
    }

    protected function resolveEntityType(Request $request): ?string
    {
        if ($request->route()?->parameter('conversation')) {
            return 'conversation';
        }

        if ($request->route()?->parameter('message')) {
            return 'message';
        }

        return 'api';
    }

    protected function resolveEntityId(Request $request): ?int
    {
        $route = $request->route();

        if ($route === null) {
            return null;
        }

        if ($id = $route->parameter('conversation')) {
            return is_numeric($id) ? (int) $id : null;
        }

        if ($id = $route->parameter('message')) {
            return is_numeric($id) ? (int) $id : null;
        }

        return null;
    }
}
