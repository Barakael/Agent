<?php

use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Schedule;

Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');

Schedule::command('trading:preflight')->dailyAt('06:45')->timezone('UTC');
Schedule::command('trading:daily-analysis')->dailyAt('06:50')->timezone('UTC');
// Midday refresh: update plan with afternoon news before FOMC/US session events
Schedule::command('trading:daily-analysis')->dailyAt('12:00')->timezone('UTC');
Schedule::command('trading:evening-review')->dailyAt('21:30')->timezone('UTC');

