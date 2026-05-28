<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('activity_logs', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->nullable()->constrained()->onDelete('cascade');
            $table->string('action'); // 'login', 'create_conversation', 'send_message', 'request_permission', etc.
            $table->string('entity_type')->nullable(); // 'conversation', 'message', 'file', 'browser', etc.
            $table->unsignedBigInteger('entity_id')->nullable();
            $table->string('method')->nullable(); // HTTP method: GET, POST, PUT, DELETE
            $table->string('endpoint')->nullable(); // API endpoint accessed
            $table->string('ip_address')->nullable();
            $table->string('user_agent')->nullable();
            $table->integer('status_code')->nullable(); // HTTP status code
            $table->text('description')->nullable();
            $table->json('data')->nullable(); // Additional context
            $table->timestamps();
            
            $table->index('user_id');
            $table->index('action');
            $table->index('created_at');
            $table->index(['user_id', 'created_at']);
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('activity_logs');
    }
};
