<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Attributes\Fillable;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

#[Fillable(['conversation_id', 'user_id', 'role', 'content', 'metadata', 'status'])]
class Message extends Model
{
    use HasFactory;

    /**
     * Get attributes that should be cast.
     */
    protected function casts(): array
    {
        return [
            'metadata' => 'json',
        ];
    }

    /**
     * Get the conversation that contains this message.
     */
    public function conversation(): BelongsTo
    {
        return $this->belongsTo(Conversation::class);
    }

    /**
     * Get the user that created this message.
     */
    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    /**
     * Scope to get only assistant messages.
     */
    public function scopeAssistant($query)
    {
        return $query->where('role', 'assistant');
    }

    /**
     * Scope to get only user messages.
     */
    public function scopeFromUser($query)
    {
        return $query->where('role', 'user');
    }

    /**
     * Scope to get completed messages.
     */
    public function scopeCompleted($query)
    {
        return $query->where('status', 'completed');
    }
}
