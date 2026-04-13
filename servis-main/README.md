# Servis MVP — Hızlı Başlangıç

## Çalıştırma

1) OSRM verisini indir:

```bash
./scripts/fetch_osrm_pbf.sh https://download.geofabrik.de/europe/monaco-latest.osm.pbf
```

2) Servisleri başlat:

```bash
docker compose up -d postgres redis osrm optimizer
```

3) Sağlık kontrolü:

```bash
curl -s http://localhost:8000/health
```

## Örnek Optimize İsteği

```bash
curl -sS -X POST http://localhost:8000/optimize \
  -H 'content-type: application/json' \
  -d '{
    "date":"2025-09-13",
    "direction":"AM",
    "school_id":1,
    "school_lat":43.7330,
    "school_lon":7.4210,
    "vehicles":[
      {"id":1,"capacity":10,"start_lat":43.7323,"start_lon":7.4206},
      {"id":2,"capacity":12,"start_lat":43.7330,"start_lon":7.4210}
    ],
    "students":[
      {"id":101,"lat":43.7327,"lon":7.4208},
      {"id":102,"lat":43.7329,"lon":7.4209}
    ]
  }'
```

Beklenen cevap örneği:

```json
{"plan_ids":[1,2],"routes":[[0,2,4],[1,3,4]]}
```
