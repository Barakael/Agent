<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('trading_analysis_decisions', function (Blueprint $table) {
            $table->id();
            $table->string('decision', 16); // GO | NO-GO
            $table->text('summary')->nullable();
            $table->json('reasons')->nullable();
            $table->json('risks')->nullable();
            $table->json('sources')->nullable();
            $table->string('source', 32)->default('ai-agent');
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('trading_analysis_decisions');
    }
};
