<?php

namespace Tests\Feature;

use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class PlatformApiTest extends TestCase
{
    use RefreshDatabase;

    public function test_authenticated_user_can_create_task_and_list_it(): void
    {
        $user = User::factory()->create();
        Sanctum::actingAs($user);

        $createResponse = $this->postJson('/api/tasks', [
            'title' => 'Run deploy checklist',
            'goal' => 'Validate release readiness',
        ]);

        $createResponse->assertCreated();
        $this->assertDatabaseHas('ai_tasks', [
            'title' => 'Run deploy checklist',
            'user_id' => $user->id,
        ]);

        $listResponse = $this->getJson('/api/tasks');
        $listResponse->assertOk()->assertJsonStructure([
            'data',
            'pagination' => ['current_page', 'total', 'per_page', 'last_page'],
        ]);
    }

    public function test_non_admin_cannot_update_permission_policies(): void
    {
        $user = User::factory()->create(['role' => 'user']);
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/permissions', [
            'scope' => 'tool',
            'resource' => 'terminal.exec',
            'access' => 'allow',
            'requires_confirmation' => true,
        ]);

        $response->assertStatus(403);
    }
}
