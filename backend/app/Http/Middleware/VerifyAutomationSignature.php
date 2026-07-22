<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class VerifyAutomationSignature
{
    public function handle(Request $request, Closure $next): Response
    {
        $secret = (string) config('services.automation.webhook_secret', '');
        if ($secret === '') {
            return response()->json(['message' => 'Automation webhook not configured'], 503);
        }

        $signature = (string) $request->header('X-Wayda-Signature', '');
        if (! str_starts_with($signature, 'sha256=')) {
            return response()->json(['message' => 'Missing or invalid X-Wayda-Signature'], 401);
        }

        $provided = substr($signature, strlen('sha256='));
        $payload = $request->getContent();
        // GET has empty body — sign the request path + query string
        if ($request->isMethod('GET') || $payload === '') {
            $payload = $request->method().'|'.$request->getRequestUri();
        }

        $expected = hash_hmac('sha256', $payload, $secret);
        if (! hash_equals($expected, $provided)) {
            return response()->json(['message' => 'Invalid automation signature'], 401);
        }

        return $next($request);
    }
}
