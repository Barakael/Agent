<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class EnsureRole
{
    public function handle(Request $request, Closure $next, string $roles): Response
    {
        $user = $request->user();
        $allowedRoles = collect(explode(',', $roles))->map(fn ($role) => trim($role));

        if ($user === null || !$allowedRoles->contains($user->role)) {
            return response()->json([
                'message' => 'Forbidden: insufficient role privileges.',
            ], 403);
        }

        return $next($request);
    }
}
