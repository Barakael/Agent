<?php

return [

    /*
    |--------------------------------------------------------------------------
    | Third Party Services
    |--------------------------------------------------------------------------
    |
    | This file is for storing the credentials for third party services such
    | as Mailgun, Postmark, AWS and more. This file provides the de facto
    | location for this type of information, allowing packages to have
    | a conventional file to locate the various service credentials.
    |
    */

    'postmark' => [
        'key' => env('POSTMARK_API_KEY'),
    ],

    'resend' => [
        'key' => env('RESEND_API_KEY'),
    ],

    'ses' => [
        'key' => env('AWS_ACCESS_KEY_ID'),
        'secret' => env('AWS_SECRET_ACCESS_KEY'),
        'region' => env('AWS_DEFAULT_REGION', 'us-east-1'),
    ],

    'slack' => [
        'notifications' => [
            'bot_user_oauth_token' => env('SLACK_BOT_USER_OAUTH_TOKEN'),
            'channel' => env('SLACK_BOT_USER_DEFAULT_CHANNEL'),
        ],
    ],

    'ai' => [
        'url' => env('AI_SERVICE_URL', 'http://localhost:8001'),
        'api_key' => env('AI_SERVICE_API_KEY', ''),
        'tool_approval_token' => env('AI_TOOL_APPROVAL_TOKEN', ''),
        'timeout' => env('AI_SERVICE_TIMEOUT', 30),
    ],

    'trading' => [
        'url' => env('TRADING_SERVICE_URL', 'http://localhost:8002'),
        'api_key' => env('TRADING_SERVICE_API_KEY', ''),
        'timeout' => env('TRADING_SERVICE_TIMEOUT', 30),
    ],

    'realtime' => [
        'transport' => env('REALTIME_TRANSPORT', 'websocket'),
    ],

];
