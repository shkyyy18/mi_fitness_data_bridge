// Generated ONLY from examples/synthetic_demo.py. Never replace with personal exports.
const SAMPLE = {
  "synthetic": true,
  "json": {
    "schema_version": "1.0",
    "source": "mi_fitness_data_bridge",
    "generated_at": "2026-07-15T20:00:00+00:00",
    "filters": {
      "dataset": null,
      "start_date": null,
      "end_date": null
    },
    "records": {
      "daily_activity": [
        {
          "id": "demo-activity-1",
          "provider": "mi_fitness",
          "source_type": "cloud_session",
          "source_record_id": null,
          "user_id": "synthetic-demo-user",
          "device_id": null,
          "timezone": "UTC",
          "collected_at": null,
          "created_at": "2026-07-15 20:00:00",
          "updated_at": "2026-07-15 20:00:00",
          "date": "2026-07-15",
          "steps": 8432,
          "distance_m": 6120.5,
          "active_kcal": 312.0,
          "total_kcal": 2210.0,
          "floors": 6,
          "active_minutes": 54
        }
      ],
      "sleep": [
        {
          "id": "demo-sleep-1",
          "provider": "mi_fitness",
          "source_type": "cloud_session",
          "source_record_id": null,
          "user_id": "synthetic-demo-user",
          "device_id": null,
          "timezone": "UTC",
          "collected_at": null,
          "created_at": "2026-07-15 20:00:00",
          "updated_at": "2026-07-15 20:00:00",
          "sleep_id": "demo-sleep-1",
          "start_at": "2026-07-14T23:20:00",
          "end_at": "2026-07-15T07:05:00",
          "duration_minutes": 465,
          "time_asleep_minutes": 441,
          "time_awake_minutes": 24,
          "sleep_score": 86,
          "is_nap": 0,
          "stages": "[{\"stage\": \"deep\", \"minutes\": 82}, {\"stage\": \"light\", \"minutes\": 271}, {\"stage\": \"rem\", \"minutes\": 88}, {\"stage\": \"awake\", \"minutes\": 24}]",
          "sleep_score_source": null
        }
      ],
      "workouts": [
        {
          "id": "demo-workout-1",
          "provider": "mi_fitness",
          "source_type": "cloud_session",
          "source_record_id": null,
          "user_id": "synthetic-demo-user",
          "device_id": null,
          "timezone": "UTC",
          "collected_at": null,
          "created_at": "2026-07-15 20:00:00",
          "updated_at": "2026-07-15 20:00:00",
          "workout_id": "demo-workout-1",
          "activity_type": "running",
          "start_at": "2026-07-15T18:30:00",
          "end_at": "2026-07-15T19:12:00",
          "duration_minutes": 42,
          "distance_m": 7200.0,
          "calories_kcal": 480.0,
          "avg_heart_rate_bpm": 148,
          "max_heart_rate_bpm": 171,
          "avg_pace_sec_per_km": null,
          "max_pace_sec_per_km": null,
          "total_steps": null
        }
      ],
      "body_measurements": [
        {
          "id": "demo-body-1",
          "provider": "mi_fitness",
          "source_type": "cloud_session",
          "source_record_id": null,
          "user_id": "synthetic-demo-user",
          "device_id": null,
          "timezone": "UTC",
          "collected_at": null,
          "created_at": "2026-07-15 20:00:00",
          "updated_at": "2026-07-15 20:00:00",
          "timestamp": "2026-07-15T07:20:00",
          "weight_kg": 72.4,
          "bmi": 23.1,
          "body_fat_pct": 18.7,
          "muscle_mass_kg": 55.3,
          "water_pct": 56.2,
          "bone_mass_kg": null,
          "visceral_fat_score": 8,
          "basal_metabolism_kcal": 1650,
          "metabolic_age": null
        }
      ],
      "heart_rate": [],
      "spo2": [],
      "stress": [],
      "abnormal_heart_beat": []
    }
  },
  "csv": {
    "daily_activity.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,date,steps,distance_m,active_kcal,total_kcal,floors,active_minutes\r\ndemo-activity-1,mi_fitness,cloud_session,,synthetic-demo-user,,UTC,,2026-07-15 20:00:00,2026-07-15 20:00:00,2026-07-15,8432,6120.5,312.0,2210.0,6,54\r\n",
    "sleep.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,sleep_id,start_at,end_at,duration_minutes,time_asleep_minutes,time_awake_minutes,sleep_score,is_nap,stages,sleep_score_source\r\ndemo-sleep-1,mi_fitness,cloud_session,,synthetic-demo-user,,UTC,,2026-07-15 20:00:00,2026-07-15 20:00:00,demo-sleep-1,2026-07-14T23:20:00,2026-07-15T07:05:00,465,441,24,86,0,\"[{\"\"stage\"\": \"\"deep\"\", \"\"minutes\"\": 82}, {\"\"stage\"\": \"\"light\"\", \"\"minutes\"\": 271}, {\"\"stage\"\": \"\"rem\"\", \"\"minutes\"\": 88}, {\"\"stage\"\": \"\"awake\"\", \"\"minutes\"\": 24}]\",\r\n",
    "workouts.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,workout_id,activity_type,start_at,end_at,duration_minutes,distance_m,calories_kcal,avg_heart_rate_bpm,max_heart_rate_bpm,avg_pace_sec_per_km,max_pace_sec_per_km,total_steps\r\ndemo-workout-1,mi_fitness,cloud_session,,synthetic-demo-user,,UTC,,2026-07-15 20:00:00,2026-07-15 20:00:00,demo-workout-1,running,2026-07-15T18:30:00,2026-07-15T19:12:00,42,7200.0,480.0,148,171,,,\r\n",
    "body_measurements.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,timestamp,weight_kg,bmi,body_fat_pct,muscle_mass_kg,water_pct,bone_mass_kg,visceral_fat_score,basal_metabolism_kcal,metabolic_age\r\ndemo-body-1,mi_fitness,cloud_session,,synthetic-demo-user,,UTC,,2026-07-15 20:00:00,2026-07-15 20:00:00,2026-07-15T07:20:00,72.4,23.1,18.7,55.3,56.2,,8,1650,\r\n",
    "heart_rate.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,timestamp,bpm,sample_type\r\n",
    "spo2.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,timestamp,spo2_pct\r\n",
    "stress.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,timestamp,stress_score,level\r\n",
    "abnormal_heart_beat.csv": "﻿id,provider,source_type,source_record_id,user_id,device_id,timezone,collected_at,created_at,updated_at,event_id,start_at,end_at,duration_seconds\r\n"
  }
};
