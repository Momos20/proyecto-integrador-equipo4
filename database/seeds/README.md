# Datos de demostración retirados

El `baseline-v0` con rankings predeterminados fue retirado por decisión del equipo. Los nuevos volúmenes ya no cargan datos simulados. Para agregar el catálogo auténtico de MovieLens 32M y crear las cuentas locales de prueba, usar `docker compose --profile setup run --rm local-setup`.

Las interacciones existentes en PostgreSQL no se borran. No utilices `down -v`.
