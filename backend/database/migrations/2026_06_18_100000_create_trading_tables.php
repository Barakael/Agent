<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('trade_journal', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->nullable()->constrained()->nullOnDelete();
            $table->string('symbol', 32);
            $table->string('direction', 8);
            $table->decimal('entry_price', 12, 5);
            $table->decimal('exit_price', 12, 5)->nullable();
            $table->decimal('stake', 12, 2);
            $table->decimal('stop_loss', 12, 5);
            $table->decimal('take_profit', 12, 5);
            $table->decimal('pnl', 12, 2)->nullable();
            $table->string('signal_source', 64)->default('confluence');
            $table->decimal('rsi_at_entry', 8, 2)->nullable();
            $table->decimal('macd_at_entry', 12, 6)->nullable();
            $table->string('contract_id', 64)->nullable();
            $table->string('status', 16)->default('open');
            $table->string('mode', 16)->default('log_only');
            $table->text('reason')->nullable();
            $table->json('metadata')->nullable();
            $table->timestamps();

            $table->index(['symbol', 'created_at']);
            $table->index('status');
        });

        Schema::create('trading_sessions', function (Blueprint $table) {
            $table->id();
            $table->date('session_date');
            $table->decimal('start_balance', 14, 2);
            $table->decimal('end_balance', 14, 2)->nullable();
            $table->decimal('cumulative_pnl', 14, 2)->default(0);
            $table->boolean('kill_switch_triggered')->default(false);
            $table->timestamp('started_at')->nullable();
            $table->timestamp('ended_at')->nullable();
            $table->timestamps();
        });

        Schema::create('trading_bot_state', function (Blueprint $table) {
            $table->id();
            $table->string('state', 16)->default('stopped');
            $table->string('mode', 16)->default('log_only');
            $table->timestamp('last_heartbeat')->nullable();
            $table->decimal('daily_pnl', 14, 2)->default(0);
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('trading_bot_state');
        Schema::dropIfExists('trading_sessions');
        Schema::dropIfExists('trade_journal');
    }
};
