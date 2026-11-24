#!/usr/bin/env python3
"""Enrich only real recommended movies using official MovieLens links and TMDB."""
import os,json,hashlib,csv,io,re,sys,ssl,urllib.request,urllib.parse
import boto3,psycopg
B="cinegraph-e4-datalake-023914826547-us-east-1"
def main():
    sm=boto3.client("secretsmanager",region_name="us-east-1")
    db=json.loads(sm.get_secret_value(SecretId=os.environ["RDS_SECRET_ARN"])["SecretString"])
    host=os.environ["RDS_ENDPOINT"]
    if not host.startswith("cinegraph-e4-postgres.") or not host.endswith(".us-east-1.rds.amazonaws.com") or db["username"]!="cinegraphadmin": raise RuntimeError("RDS_TARGET")
    s3=boto3.client("s3",region_name="us-east-1")
    links=s3.get_object(Bucket=B,Key="reference/movielens32m/links.csv")["Body"].read()
    if hashlib.md5(links).hexdigest()!="8f033867bcb4e6be8792b21468b4fa6e": raise RuntimeError("LINKS_MD5")
    mapping={int(r["movieId"]):int(r["tmdbId"]) for r in csv.DictReader(io.StringIO(links.decode("utf-8-sig"))) if r["tmdbId"].isdigit()}
    with psycopg.connect(host=host,port=5432,dbname="cinegraph",user=db["username"],password=db["password"],sslmode="verify-full",sslrootcert="/tmp/cinegraph-rds-ca.pem",connect_timeout=10) as conn:
        movies=conn.execute("SELECT DISTINCT m.movie_id,m.title FROM movies m JOIN recommendations r ON r.movie_id=m.movie_id WHERE r.model_version='a9-miguel-diario' AND r.cutoff_week='2023-06-15' ORDER BY m.movie_id").fetchall()
        try:
            token=json.loads(sm.get_secret_value(SecretId="cinegraph-e4-tmdb")["SecretString"])["read_token"]
        except sm.exceptions.ResourceNotFoundException:
            print("TMDB_TOKEN_REQUIRED: no changes; configure cinegraph-e4-tmdb in Secrets Manager",flush=True)
            return
        if not isinstance(token,str) or not token.strip(): raise RuntimeError("TMDB_TOKEN_INVALID")
        updates=[]; missing=[]
        for mid,title in movies:
            tid=mapping.get(mid)
            if not tid: missing.append(title); continue
            req=urllib.request.Request(f"https://api.themoviedb.org/3/movie/{tid}/images?include_image_language=es,en,null",headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
            try:
                with urllib.request.urlopen(req,timeout=20) as res: data=json.load(res)
            except urllib.error.HTTPError as e:
                if e.code==404: missing.append(title); continue
                raise RuntimeError("TMDB_HTTP_"+str(e.code)) from None
            posters=[p for p in data.get("posters",[]) if p.get("iso_639_1") in ("es","en",None) and re.fullmatch(r"/[A-Za-z0-9_-]+\.(jpg|png|webp)",str(p.get("file_path","")),re.I)]
            posters.sort(key=lambda p:({"es":0,"en":1,None:2}[p.get("iso_639_1")],-p.get("vote_average",0),-p.get("vote_count",0)))
            if not posters: missing.append(title); continue
            url="https://image.tmdb.org/t/p/w500"+posters[0]["file_path"]
            updates.append((url,mid))
        for url,mid in updates:
            conn.execute("UPDATE movies SET poster_url=%s,updated_at=NOW() WHERE movie_id=%s",(url,mid))
    print(json.dumps({"poster_updates":len(updates),"distinct_recommended_movies":len(movies),"unavailable":missing},ensure_ascii=False))
    print("A9_POSTERS_UPDATED")
if __name__=="__main__":
    try: main()
    except Exception as e:
        print("POSTERS_FAILED:",type(e).__name__,file=sys.stderr);sys.exit(1)
