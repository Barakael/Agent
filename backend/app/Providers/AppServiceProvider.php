<?php

namespace App\Providers;

use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        //
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        RateLimiter::for('auth-login', function (Request $request) {
            return [
                Limit::perMinute(10)->by($request->ip()),
                Limit::perMinute(30)->by($request->input('email', 'unknown')),
            ];
        });

        RateLimiter::for('high-cost-ai', function (Request $request) {
            $identity = $request->user()?->id ?? $request->ip();
            return Limit::perMinute(20)->by('ai-'.$identity);
        });
    }
}
