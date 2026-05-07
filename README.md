# Servis MVP — School Shuttle Route Optimization

Bu proje, okul servis araçları için öğrenci toplama ve rota planlama sürecini optimize etmeye yönelik hazırlanmış bir **MVP rota optimizasyon servisidir**.

Sistem; öğrenci konumları, araç kapasiteleri, okul konumu, zaman pencereleri ve servis yönü gibi bilgileri alarak uygun servis rotaları üretir. Projede rota optimizasyonu için **OR-Tools**, mesafe/süre matrisi için **OSRM**, servis API’si için **FastAPI**, veri saklama için **PostgreSQL/PostGIS**, cache ve idempotency işlemleri için **Redis** kullanılmaktadır.

---

## Projenin Amacı

Okul servislerinde rota planlama problemi; araç kapasitesi, öğrenci konumları, zaman pencereleri, okul varış zamanı ve servis süresi gibi birçok kısıtı aynı anda dikkate almayı gerektirir.

Bu proje, bu problemi bir optimizasyon problemi olarak ele alır ve aşağıdaki sorulara çözüm üretmeyi hedefler:

- Hangi öğrenci hangi servis aracına atanmalı?
- Araçlar öğrencileri hangi sırayla almalı?
- Araç kapasitesi aşılmadan rota nasıl oluşturulmalı?
- Okula varış zamanı ve öğrenci zaman pencereleri nasıl korunmalı?
- Bazı öğrenciler atanamazsa sistem bunu nasıl raporlamalı?
- Üretilen rota planları nasıl kaydedilmeli ve takip edilmeli?

---

## Temel Özellikler

- FastAPI tabanlı optimizer servisi
- Docker Compose ile çok servisli çalışma ortamı
- PostgreSQL/PostGIS veritabanı desteği
- Redis cache kullanımı
- OSRM ile yolculuk süresi matrisi üretimi
- OR-Tools ile CVRPTW çözümü
- Araç kapasitesi kısıtı
- Öğrenci zaman penceresi kısıtı
- Okul varış deadline desteği
- Servis aracı vardiya başlangıç/bitiş zamanı desteği
- Atanamayan öğrenci raporlama
- Rota planlarının veritabanına kaydedilmesi
- Stop event takibi
- Idempotency key desteği
- Parent no-show durumunda yeniden optimizasyon akışı

---

## Kullanılan Teknolojiler

| Teknoloji | Kullanım Amacı |
|---|---|
| Python | Backend ve optimizasyon servisi |
| FastAPI | REST API geliştirme |
| Pydantic | Request/response veri doğrulama |
| OR-Tools | Rota optimizasyonu |
| OSRM | Yolculuk süresi matrisi üretimi |
| PostgreSQL | Rota ve event verilerinin saklanması |
| PostGIS | Coğrafi veri desteği |
| Redis | Cache ve idempotency yönetimi |
| Docker | Servislerin container ortamında çalıştırılması |
| Docker Compose | Çok servisli mimarinin ayağa kaldırılması |
| httpx / aiohttp | Asenkron HTTP istekleri |
| NumPy | Matris işlemleri |

---

## Proje Yapısı

```text
servis-main/
│
├── db/
│   └── init.sql
│
├── scripts/
│   └── fetch_osrm_pbf.sh
│
├── services/
│   └── optimizer/
│       ├── app/
│       │   ├── main.py
│       │   ├── solver.py
│       │   └── traffic.py
│       │
│       ├── Dockerfile
│       └── requirements.txt
│
├── docker-compose.yml
└── README.md
