<?php

namespace Database\Seeders;

use App\Models\User;
use Illuminate\Database\Console\Seeds\WithoutModelEvents;
use Illuminate\Database\Seeder;

class DatabaseSeeder extends Seeder
{
    use WithoutModelEvents;

    /**
     * Seed the application's database.
     *
     * Avoids Eloquent factories so `php artisan db:seed` works on production
     * installs that use `composer install --no-dev` (no fakerphp/faker).
     */
    public function run(): void
    {
        User::query()->updateOrCreate(
            ['email' => 'admin@wayda.co.tz'],
            [
                'name' => 'Admin',
                'password' => 'password',
                'role' => 'admin',
                'email_verified_at' => now(),
            ]
        );

        User::query()->updateOrCreate(
            ['email' => 'test@example.com'],
            [
                'name' => 'Test User',
                'password' => 'password',
                'role' => 'user',
                'email_verified_at' => now(),
            ]
        );
    }
}
