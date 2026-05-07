# Servis MVP — School Shuttle Route Optimization API

Bu proje, okul servisleri için **rota optimizasyonu**, **öğrenci/araç kapasite yönetimi**, **zaman penceresi kontrolü**, **rota planı kaydı** ve **servis durak olaylarının takibi** amacıyla geliştirilmiş bir MVP backend sistemidir.

Projenin merkezinde FastAPI tabanlı bir optimizer servisi bulunur. Servis, öğrenci ve araç bilgilerini alır, OSRM üzerinden süre matrisi üretir, OR-Tools ile rota optimizasyonu yapar, sonuçları PostgreSQL/PostGIS veritabanına kaydeder ve Redis üzerinden cache/idempotency desteği sağlar.

---

## İçindekiler

- [Proje Amacı](#proje-amacı)
- [Temel Özellikler](#temel-özellikler)
- [Mimari Yapı](#mimari-yapı)
- [Klasör Yapısı](#klasör-yapısı)
- [Kullanılan Teknolojiler](#kullanılan-teknolojiler)
- [Servisler](#servisler)
- [Veritabanı Şeması](#veritabanı-şeması)
- [API Endpointleri](#api-endpointleri)
- [Kurulum](#kurulum)
- [Çalıştırma](#çalıştırma)
- [Örnek Optimize İsteği](#örnek-optimize-isteği)
- [Örnek Cevap](#örnek-cevap)
- [Projenin Güçlü Yönleri](#projenin-güçlü-yönleri)
- [Geliştirme Fikirleri](#geliştirme-fikirleri)
- [Author](#author)

---

## Proje Amacı

Bu projenin amacı, okul servislerinin günlük rota planlamasını daha verimli hale getirebilecek bir backend altyapısı oluşturmaktır.

Sistem şu problem üzerine kuruludur:

> Belirli bir okul, öğrenci listesi ve servis araçları verildiğinde; araç kapasitelerini, öğrenci lokasyonlarını, zaman pencerelerini ve okul varış hedefini dikkate alarak uygun servis rotalarını üretmek.

Bu problem, klasik bir **Vehicle Routing Problem (VRP)** varyantıdır. Projede özellikle şu kısıtlar dikkate alınır:

- Araç kapasitesi
- Öğrenci konumları
- Öğrenci zaman pencereleri
- Araç vardiya başlangıç/bitiş zamanı
- Okula varış deadline'ı
- Maksimum yolculuk süresi
- Servis süresi
- Öncelik ve drop penalty mantığı
- Atanamayan öğrenci durumları
- Yeniden optimizasyon senaryosu

---

## Temel Özellikler

- FastAPI tabanlı REST API
- Docker Compose ile çok servisli çalışma ortamı
- PostgreSQL/PostGIS veritabanı
- Redis cache desteği
- OSRM ile yolculuk süresi matrisi üretimi
- OR-Tools ile CVRPTW çözümü
- Kapasite kısıtı yönetimi
- Zaman penceresi yönetimi
- Okul varış deadline kontrolü
- Öğrenci bazlı maksimum yolculuk süresi kontrolü
- Rota planlarını veritabanına kaydetme
- Plan durumunu sorgulama
- Durak olaylarını kaydetme
- Idempotency key desteği
- Parent no-show senaryosu için yeniden optimizasyon
- Matrix cache ile tekrar eden OSRM çağrılarını azaltma

---

## Mimari Yapı

Proje dört ana servis üzerinden çalışır:

```text
Client / API Consumer
        |
        v
FastAPI Optimizer Service
        |
        |---- PostgreSQL / PostGIS
        |
        |---- Redis
        |
        |---- OSRM Routing Engine
        |
        v
OR-Tools CVRPTW Solver
```

### Akış

1. Kullanıcı `/optimize` endpointine okul, araç ve öğrenci bilgilerini gönderir.
2. Optimizer servisi tüm koordinatları hazırlar.
3. OSRM üzerinden yolculuk süresi matrisi alınır.
4. Matris Redis üzerinde cache'lenir.
5. OR-Tools solver kapasite ve zaman pencerelerine göre rota üretir.
6. Üretilen rota planları PostgreSQL veritabanına kaydedilir.
7. API, plan ID'leri, rota detayları, metrikler ve uyarılarla birlikte cevap döner.

---

## Klasör Yapısı

Repository içinde ana proje `servis-main` klasörü altında tutulmaktadır.

```text
servis/
└── servis-main/
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
```

---

## Klasör ve Dosya Açıklamaları

### `db/init.sql`

Veritabanı başlangıç şemasını oluşturur.

Bu dosyada şu tablolar tanımlanır:

- `route_plan`
- `stop_events`
- `idempotency_keys`

Ayrıca rota planları ve durak olayları için indexler oluşturulur.

### `scripts/fetch_osrm_pbf.sh`

OSRM için gerekli `.osm.pbf` harita verisini indirir.

Varsayılan olarak İstanbul/Marmara bölgesine ait Geofabrik verisini kullanır. Farklı bir bölge kullanılmak istenirse script'e URL parametresi verilebilir.

### `services/optimizer/app/main.py`

FastAPI uygulamasının ana dosyasıdır.

Bu dosyada:

- API modelleri
- `/health`
- `/optimize`
- `/events`
- `/plan/{plan_id}`
- `/plan/{plan_id}/status`
- `/parent/no-show`

endpointleri tanımlanmıştır.

Ayrıca OSRM, Redis, PostgreSQL bağlantıları ve rota planı kaydetme işlemleri de bu dosyada yönetilir.

### `services/optimizer/app/solver.py`

Rota optimizasyon algoritmasını içerir.

Bu dosyada `AdvancedCVRPTWSolver` sınıfı yer alır. Solver, OR-Tools kullanarak kapasite kısıtlı ve zaman pencereli araç rotalama problemi çözer.

Desteklenen temel kısıtlar:

- Araç kapasitesi
- Öğrenci talebi/demand
- Öğrenci zaman penceresi
- Araç vardiya zamanı
- Okul varış deadline'ı
- Drop penalty
- Öğrenci önceliği
- Partial solution desteği

### `services/optimizer/app/traffic.py`

Trafik ve süre matrisi yönetimi için yardımcı sınıfları içerir.

Bu dosyada iki önemli yapı bulunur:

- `MultiSourceTrafficIntegrator`
- `SmartMatrixCache`

`SmartMatrixCache`, OSRM'den alınan süre matrislerini Redis üzerinde cache'ler. Böylece aynı koordinat setleri için tekrar tekrar OSRM isteği yapılmaz.

### `services/optimizer/Dockerfile`

Optimizer servisinin Docker imajını oluşturur.

Python 3.11 slim imajını kullanır, gerekli paketleri yükler ve FastAPI uygulamasını `uvicorn` ile çalıştırır.

### `services/optimizer/requirements.txt`

Optimizer servisinin Python bağımlılıklarını içerir.

Temel paketler:

- FastAPI
- Uvicorn
- Pydantic
- HTTPX
- Psycopg
- Redis
- OR-Tools
- NumPy
- aiohttp

### `docker-compose.yml`

Tüm sistemi birlikte ayağa kaldırır.

Tanımlı servisler:

- `postgres`
- `redis`
- `osrm`
- `optimizer`

---

## Kullanılan Teknolojiler

| Teknoloji | Kullanım Amacı |
|---|---|
| Python | Ana backend geliştirme dili |
| FastAPI | REST API geliştirme |
| Pydantic | Request/response veri doğrulama |
| OR-Tools | Rota optimizasyonu |
| OSRM | Yolculuk süresi matrisi üretme |
| PostgreSQL | Rota ve olay kayıtlarını saklama |
| PostGIS | Konumsal veri altyapısı |
| Redis | Cache ve idempotency desteği |
| Docker | Servisleri container içinde çalıştırma |
| Docker Compose | Çok servisli lokal geliştirme ortamı |
| HTTPX / aiohttp | Asenkron HTTP istekleri |
| NumPy | Matris işlemleri |

---

## Servisler

### PostgreSQL / PostGIS

Rota planları ve servis olayları burada saklanır.

Docker Compose içinde `postgis/postgis:16-3.4` imajı kullanılır.

### Redis

Redis iki amaçla kullanılır:

1. OSRM süre matrislerini cache'lemek
2. Idempotency key kontrolü yapmak

### OSRM

OSRM, gerçek yol ağı üzerinden iki nokta arasındaki tahmini yolculuk süresini üretmek için kullanılır.

Sistem, OSRM'in `table` endpointini kullanarak araç, öğrenci ve okul koordinatları arasında süre matrisi oluşturur.

### Optimizer

FastAPI tabanlı ana servistir. Kullanıcıdan rota optimizasyon isteğini alır, gerekli matrisi hazırlar, solver'ı çalıştırır ve sonucu döner.

---

## Veritabanı Şeması

### `route_plan`

Rota planlarını saklar.

| Kolon | Açıklama |
|---|---|
| `id` | Plan ID |
| `date` | Plan tarihi |
| `direction` | AM / PM yön bilgisi |
| `vehicle_id` | Araç ID |
| `student_sequence` | Rotadaki öğrenci sırası |
| `eta_sequence` | Tahmini varış zamanları |
| `version` | Plan versiyonu |
| `created_at` | Oluşturulma zamanı |
| `is_active` | Aktiflik bilgisi |

### `stop_events`

Servis durak olaylarını saklar.

| Kolon | Açıklama |
|---|---|
| `id` | Kayıt ID |
| `event_id` | UUID olay ID |
| `ts` | Olay zamanı |
| `trip_id` | Sefer/plan ID |
| `vehicle_id` | Araç ID |
| `student_id` | Öğrenci ID |
| `event_type` | ARRIVE, PICKED_UP, DEPART, MANUAL_SKIP |
| `lat` | Olay lokasyonu latitude |
| `lon` | Olay lokasyonu longitude |
| `seq_no` | Sıra numarası |
| `processed` | İşlenme durumu |

### `idempotency_keys`

Tekrarlı event kayıtlarını engellemek için idempotency anahtarlarını saklar.

---

## API Endpointleri

### `GET /health`

Servis sağlık durumunu kontrol eder.

Kontrol edilen bileşenler:

- PostgreSQL
- Redis
- OSRM

Örnek:

```bash
curl -s http://localhost:8000/health
```

---

### `POST /optimize`

Araç ve öğrenci bilgilerine göre rota planı üretir.

Bu endpoint:

- Koordinatlardan OSRM süre matrisi üretir.
- Matris cache kontrolü yapar.
- OR-Tools solver'ı çalıştırır.
- Rota detaylarını oluşturur.
- Planları veritabanına kaydeder.
- Plan ID'lerini ve rota detaylarını döner.

---

### `POST /events`

Servis sırasında oluşan durak olaylarını kaydeder.

Desteklenen olay tipleri:

- `ARRIVE`
- `PICKED_UP`
- `DEPART`
- `MANUAL_SKIP`

Ayrıca `idempotency-key` header'ı ile duplicate event gönderimleri engellenebilir.

---

### `GET /plan/{plan_id}`

Belirli bir rota planını getirir.

Dönen bilgiler:

- Plan ID
- Tarih
- Yön
- Araç ID
- Öğrenci sırası
- ETA bilgileri
- Versiyon
- Aktiflik durumu

---

### `GET /plan/{plan_id}/status`

Belirli bir planın durak bazlı durumunu getirir.

Öğrenciler için durumlar:

- `pending`
- `arrived`
- `picked_up`
- `skipped`

---

### `POST /parent/no-show`

Bir öğrencinin servise binmeyeceği durumda yeniden optimizasyon yapar.

Bu endpoint:

1. İlgili plan snapshot'ını Redis'ten alır.
2. Öğrenciyi listeden çıkarır.
3. Yeni süre matrisi üretir.
4. Solver'ı yeniden çalıştırır.
5. Yeni rota planlarını kaydeder.

---

## Kurulum

Projeyi klonlayın:

```bash
git clone https://github.com/ElanurBUZLUK/servis.git
cd servis/servis-main
```

Docker ve Docker Compose kurulu olmalıdır.

Kontrol etmek için:

```bash
docker --version
docker compose version
```

---

## Çalıştırma

### 1. OSRM harita verisini indirin

Varsayılan bölge için:

```bash
./scripts/fetch_osrm_pbf.sh
```

Farklı bir bölge kullanmak için:

```bash
./scripts/fetch_osrm_pbf.sh https://download.geofabrik.de/europe/monaco-latest.osm.pbf
```

Bu işlem `data/osm/region.osm.pbf` dosyasını oluşturur.

---

### 2. Servisleri başlatın

```bash
docker compose up -d postgres redis osrm optimizer
```

---

### 3. Sağlık kontrolü yapın

```bash
curl -s http://localhost:8000/health
```

Beklenen örnek cevap:

```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "osrm": "ok"
}
```

---

## Örnek Optimize İsteği

```bash
curl -sS -X POST http://localhost:8000/optimize \
  -H 'content-type: application/json' \
  -d '{
    "date": "2025-09-13",
    "direction": "AM",
    "school_id": 1,
    "school_lat": 43.7330,
    "school_lon": 7.4210,
    "school_arrival_deadline": "08:30",
    "vehicles": [
      {
        "id": 1,
        "capacity": 10,
        "start_lat": 43.7323,
        "start_lon": 7.4206,
        "shift_start_ts": "07:00",
        "shift_end_ts": "09:00"
      },
      {
        "id": 2,
        "capacity": 12,
        "start_lat": 43.7330,
        "start_lon": 7.4210,
        "shift_start_ts": "07:00",
        "shift_end_ts": "09:00"
      }
    ],
    "students": [
      {
        "id": 101,
        "lat": 43.7327,
        "lon": 7.4208,
        "tw_lo": "07:15",
        "tw_hi": "08:10",
        "max_ride_min": 45,
        "service_time_sec": 60,
        "demand": 1,
        "priority": 1
      },
      {
        "id": 102,
        "lat": 43.7329,
        "lon": 7.4209,
        "tw_lo": "07:20",
        "tw_hi": "08:15",
        "max_ride_min": 45,
        "service_time_sec": 60,
        "demand": 1,
        "priority": 1
      }
    ]
  }'
```

---

## Örnek Cevap

```json
{
  "plan_ids": [1, 2],
  "routes": [[0, 2, 4], [1, 3, 4]],
  "route_details": [
    {
      "vehicle_id": 1,
      "capacity": 10,
      "route_duration_sec": 820,
      "stops": [
        {
          "node_index": 0,
          "eta": "2025-09-13T07:15:00",
          "type": "VEHICLE_START"
        },
        {
          "node_index": 2,
          "eta": "2025-09-13T07:25:00",
          "type": "PICKUP",
          "student_id": 101,
          "ride_time_sec": 600
        },
        {
          "node_index": 4,
          "eta": "2025-09-13T07:35:00",
          "type": "SCHOOL"
        }
      ]
    }
  ],
  "solver_status": "SUCCESS",
  "unassigned_students": [],
  "objective_value": 1234,
  "solve_time_ms": 120,
  "metrics": {
    "total_route_duration_sec": 820,
    "assigned_students": 2,
    "unassigned_students": 0,
    "max_ride_sec": 600
  },
  "warnings": []
}
```

---

## Optimizasyon Mantığı

Projedeki temel optimizasyon problemi **CVRPTW** olarak düşünülebilir:

> Capacitated Vehicle Routing Problem with Time Windows

Yani sistem hem araç kapasitesini hem de zaman pencerelerini dikkate alır.

Solver tarafında:

- Küçük problemler için `PATH_CHEAPEST_ARC`
- Orta ve büyük problemler için `SAVINGS`
- Yerel arama için `GUIDED_LOCAL_SEARCH`, `SIMULATED_ANNEALING` ve `TABU_SEARCH`

stratejileri kullanılmaktadır.

Problem boyutuna göre solver konfigürasyonu otomatik seçilir.

---

## Cache Mantığı

Süre matrisi oluşturmak maliyetli bir işlemdir. Bu nedenle `SmartMatrixCache` sınıfı aynı koordinat dizilimi için tekrar OSRM çağrısı yapılmasını engeller.

Cache key oluşturulurken:

- Koordinatlar sıralı şekilde korunur.
- Longitude/latitude değerleri normalize edilir.
- SHA-256 hash kullanılır.
- Matris Redis üzerinde belirli süreyle saklanır.

Bu yaklaşım özellikle aynı gün, aynı okul ve benzer öğrenci/araç setleriyle yapılan tekrar optimizasyonlarda performans avantajı sağlar.

---

## No-Show Reoptimization

`/parent/no-show` endpointi, öğrencinin servise binmeyeceğini bildirdiği durumda yeniden optimizasyon yapar.

Akış:

```text
Parent no-show request
        |
        v
Redis snapshot okunur
        |
        v
Öğrenci listeden çıkarılır
        |
        v
Yeni süre matrisi alınır
        |
        v
Solver yeniden çalışır
        |
        v
Yeni planlar PostgreSQL'e kaydedilir
```

Bu yapı, gerçek servis operasyonlarında son dakika değişikliklerine karşı daha esnek bir rota yönetimi sağlar.

---

## Projenin Güçlü Yönleri

Bu proje yalnızca basit bir API örneği değildir. Gerçek operasyonel bir servis optimizasyon probleminin temel bileşenlerini bir araya getirir.

Öne çıkan güçlü yönler:

- Gerçek rota motoru olarak OSRM kullanılması
- OR-Tools ile gerçek optimizasyon problemi çözülmesi
- Kapasite ve zaman penceresi kısıtlarının modele dahil edilmesi
- Docker Compose ile reproducible çalışma ortamı
- PostgreSQL ile rota planlarının kalıcı saklanması
- Redis ile cache ve idempotency desteği
- Parent no-show gibi gerçek operasyonel senaryoya yönelik yeniden optimizasyon
- API seviyesinde plan, event ve status yönetimi
- Modüler `main.py`, `solver.py`, `traffic.py` ayrımı

---

## Geliştirme Fikirleri

Bu MVP üzerine aşağıdaki geliştirmeler eklenebilir:

- JWT tabanlı authentication
- Role-based authorization
- Admin panel / frontend arayüzü
- Öğrenci ve araç CRUD endpointleri
- Okul bazlı çoklu tenant yapısı
- Gerçek zamanlı araç konumu takibi
- WebSocket ile canlı rota durumu
- Trafik API entegrasyonlarının aktif kullanımı
- Test suite: unit, integration, API tests
- CI/CD pipeline
- OpenAPI dokümantasyonunun genişletilmesi
- Rota haritası görselleştirme
- Plan versiyonlama ve rollback
- Çoklu okul desteği
- SLA/ETA sapma analizi
- Plan kalitesi metriklerinin genişletilmesi

---

## Örnek Kullanım Senaryosu

Bu sistem şu tarz bir servis operasyonu için kullanılabilir:

1. Sabah servis planı için öğrenci ve araç listesi girilir.
2. Sistem araç kapasitelerine ve öğrenci lokasyonlarına göre rota üretir.
3. Şoför rota planını takip eder.
4. Her durakta `ARRIVE`, `PICKED_UP`, `DEPART` olayları gönderilir.
5. Veli öğrencinin gelmeyeceğini bildirirse `/parent/no-show` ile rota yeniden optimize edilir.
6. Operasyon ekibi `/plan/{plan_id}/status` ile rota durumunu izler.
