FROM php:8.3-cli

RUN apt-get update && apt-get install -y git unzip sqlite3 libsqlite3-dev \
    && docker-php-ext-install pdo_sqlite \
    && curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

WORKDIR /var/www/html
COPY . .
RUN composer install --no-dev --optimize-autoloader || composer install

EXPOSE 8000
CMD ["php", "artisan", "serve", "--host=0.0.0.0", "--port=8000"]
