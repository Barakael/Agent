<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class TradingAnalysisDecision extends Model
{
    protected $fillable = [
        'decision',
        'summary',
        'reasons',
        'risks',
        'recommendation',
        'sources',
        'source',
    ];

    protected $casts = [
        'reasons' => 'array',
        'risks' => 'array',
        'recommendation' => 'array',
        'sources' => 'array',
    ];
}
