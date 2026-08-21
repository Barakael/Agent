<?php

use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Schedule;

Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');

// FX majors only: market is shut Fri 20:55–Sun 21:05 UTC — no weekday analysis.
Schedule::command('trading:preflight')
    ->weekdays()
    ->dailyAt('06:45')
    ->timezone('UTC');

// Align with Cursor Automation slots: morning / London–NY overlap / US afternoon.
Schedule::command('trading:daily-analysis')
    ->weekdays()
    ->dailyAt('06:50')
    ->timezone('UTC');
Schedule::command('trading:daily-analysis')
    ->weekdays()
    ->dailyAt('12:00')
    ->timezone('UTC');
Schedule::command('trading:daily-analysis')
    ->weekdays()
    ->dailyAt('16:00')
    ->timezone('UTC');

Schedule::command('trading:evening-review')
    ->weekdays()
    ->dailyAt('21:30')
    ->timezone('UTC');

