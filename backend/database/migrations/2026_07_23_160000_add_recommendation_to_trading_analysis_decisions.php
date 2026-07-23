<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('trading_analysis_decisions', function (Blueprint $table) {
            $table->json('recommendation')->nullable()->after('risks');
        });
    }

    public function down(): void
    {
        Schema::table('trading_analysis_decisions', function (Blueprint $table) {
            $table->dropColumn('recommendation');
        });
    }
};
