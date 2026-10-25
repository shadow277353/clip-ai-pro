import os, re, json, uuid, shutil, subprocess, threading, time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

ROOT=Path(__file__).parent.resolve()
DATA=Path(os.getenv("DATA_DIR", str(ROOT/"data")))
UPLOADS=DATA/"uploads"; EXPORTS=DATA/"exports"; JOBS=DATA/"jobs"
for p in (UPLOADS, EXPORTS, JOBS): p.mkdir(parents=True, exist_ok=True)
MAX_MB=int(os.getenv("MAX_UPLOAD_MB","500"))
WHISPER_MODEL=os.getenv("WHISPER_MODEL","base")
app=FastAPI(title="ClipAI Pro", version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
app.mount("/files",StaticFiles(directory=str(EXPORTS)),name="files")

def run(cmd, timeout=None):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)

def save_job(job):
    (JOBS/f"{job['id']}.json").write_text(json.dumps(job,ensure_ascii=False,indent=2))
def get_job(jid):
    p=JOBS/f"{jid}.json"
    if not p.exists(): raise HTTPException(404,"Job not found")
    return json.loads(p.read_text())
def update_job(jid, **kw):
    j=get_job(jid); j.update(kw); save_job(j); return j
def duration(path):
    r=run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)])
    if r.returncode: return 0.0
    try:return float(r.stdout.strip())
    except:return 0.0
def clean_name(s):
    return re.sub(r"[^a-zA-Z0-9_-]+","-",s).strip("-")[:70] or "clip"
def transcribe(path):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Speech AI is not installed. Install requirements.txt or set up the hosted backend.")
    model=WhisperModel(WHISPER_MODEL,device=os.getenv("WHISPER_DEVICE","cpu"),compute_type=os.getenv("WHISPER_COMPUTE","int8"))
    segs, info=model.transcribe(str(path), word_timestamps=True, vad_filter=True)
    out=[]
    for s in segs:
        words=[]
        if s.words:
            words=[{"start":float(w.start),"end":float(w.end),"word":w.word} for w in s.words]
        out.append({"start":float(s.start),"end":float(s.end),"text":s.text.strip(),"words":words})
    return {"language":info.language,"segments":out}
HOOKS=["how to","the truth","nobody tells","mistake","secret","why","never","always","changed my life","i learned","you need to","here's why","the problem","incredible","imagine","listen","honestly","the reason","what if","finally","best way","worst"]
def score_segment(text, length):
    t=text.lower(); score=0
    score+=sum(2.2 for h in HOOKS if h in t)
    score+=min(len(re.findall(r"[!?]",text))*1.2,3)
    score+=min(len(re.findall(r"\b(i|you|your|we|they|because|but|secret|money|life|love|fear|fail|win)\b",t))*0.18,3)
    if 8 <= length <= 55: score+=2
    elif length < 4: score-=2
    score+=min(len(text)/220,1)
    return round(score,2)
def pick_clips(transcript, total, count=10, min_len=15, max_len=45):
    segs=transcript.get("segments",[])
    if not segs: return []
    candidates=[]
    # Build windows starting at transcript segment boundaries; favor coherent lengths.
    for i,s in enumerate(segs):
        start=max(0,float(s["start"])-1.0)
        for j in range(i,min(len(segs),i+18)):
            end=float(segs[j]["end"])+0.25
            length=end-start
            if length>max_len: break
            if length<min_len: continue
            text=" ".join(x["text"] for x in segs[i:j+1]).strip()
            candidates.append({"start":start,"end":min(end,total),"text":text,"score":score_segment(text,length)})
    if not candidates:
        for s in segs:
            start=max(0,float(s["start"])); end=min(total,max(start+2,float(s["end"])))
            candidates.append({"start":start,"end":end,"text":s["text"],"score":score_segment(s["text"],end-start)})
    candidates.sort(key=lambda x:x["score"],reverse=True)
    chosen=[]
    for c in candidates:
        if all(c["end"] <= x["start"] or c["start"] >= x["end"] for x in chosen):
            chosen.append(c)
        if len(chosen)>=count: break
    chosen.sort(key=lambda x:x["start"])
    for i,c in enumerate(chosen,1):
        c.update({"id":str(uuid.uuid4())[:8],"title":make_title(c["text"]),"number":i})
    return chosen
def make_title(text):
    words=re.findall(r"\b[\w’'-]+\b",text)
    if not words:return "A moment worth sharing"
    t=" ".join(words[:9]).strip(" ,.!?")
    return (t[0].upper()+t[1:] if t else "A moment worth sharing") + ("…" if len(words)>9 else "")
def srt_time(sec):
    ms=int(max(0,sec)*1000); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
def write_srt(transcript,start,end,out):
    lines=[]; idx=1
    for s in transcript.get("segments",[]):
        a=max(float(s["start"]),start); b=min(float(s["end"]),end)
        if b<=a: continue
        text=s["text"].strip()
        if not text: continue
        lines += [str(idx),f"{srt_time(a-start)} --> {srt_time(b-start)}",text,""]
        idx+=1
    Path(out).write_text("\n".join(lines),encoding="utf-8")
def render_clip(source, clip, transcript, burn=True, ratio="9:16", quality=720):
    cid=clip.get("id",str(uuid.uuid4())[:8]); base=clean_name(clip.get("title","clip"))
    out=EXPORTS/f"{base}-{cid}.mp4"
    s=max(0,float(clip["start"])); e=float(clip["end"])
    if e<=s: raise ValueError("Clip end must be after start")
    srt=EXPORTS/f"{base}-{cid}.srt"
    write_srt(transcript,s,e,srt)
    if ratio=="9:16": w,h=404,720
    elif ratio=="1:1": w,h=720,720
    else: w,h=1280,720
    w=int(w*int(quality)/720); h=int(h*int(quality)/720)
    # scale+crop, with optional subtitles burned in; subtitles path escaped for ffmpeg filter.
    vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if burn:
        escaped=str(srt.resolve()).replace("\\","/").replace(":","\\:").replace("'","\\'")
        vf+=f",subtitles='{escaped}':force_style='FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=60'"
    cmd=["ffmpeg","-y","-ss",str(s),"-i",str(source),"-t",str(e-s),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k","-movflags","+faststart",str(out)]
    r=run(cmd,timeout=1800)
    if r.returncode: raise RuntimeError("FFmpeg failed: "+r.stderr[-1400:])
    clip.update({"file":out.name,"url":f"/files/{out.name}","subtitle_file":srt.name})
    return clip
def analyze_worker(jid):
    j=get_job(jid)
    try:
        update_job(jid,status="analyzing",progress=10,message="Reading video metadata…")
        src=UPLOADS/j["source_file"]
        d=duration(src)
        if d<=0: raise RuntimeError("Could not read video duration. Try an MP4 file.")
        update_job(jid,duration=d,progress=20,message="Transcribing speech with Whisper…")
        tr=transcribe(src)
        clips=pick_clips(tr,d,count=10)
        update_job(jid,transcript=tr,clips=clips,progress=100,status="ready",message=f"Analysis complete. Found {len(clips)} suggested clips.",language=tr.get("language"))
    except Exception as ex:
        update_job(jid,status="error",message=str(ex),progress=100)
def background_render(jid, clip_id, ratio, quality, burn):
    j=get_job(jid)
    try:
        clip=next((c for c in j["clips"] if c["id"]==clip_id),None)
        if not clip: raise RuntimeError("Clip not found")
        update_job(jid,status="rendering",message="Rendering clip with FFmpeg…")
        rendered=render_clip(UPLOADS/j["source_file"],dict(clip),j.get("transcript",{}),burn,ratio,quality)
        clips=[rendered if c["id"]==clip_id else c for c in j["clips"]]
        update_job(jid,clips=clips,status="ready",message="Clip rendered and ready to download.")
    except Exception as ex:
        update_job(jid,status="error",message=str(ex))
@app.get("/",response_class=HTMLResponse)
def home(): return (ROOT/"static"/"index.html").read_text(encoding="utf-8")
@app.get("/api/health")
def health(): return {"ok":True,"app":"ClipAI Pro","ffmpeg":shutil.which("ffmpeg") is not None}
@app.post("/api/upload")
async def upload(file:UploadFile=File(...)):
    ext=Path(file.filename or "").suffix.lower()
    if ext not in {".mp4",".mov",".m4v",".webm",".mkv",".avi"}: raise HTTPException(400,"Upload a video file (MP4/MOV/WebM/MKV/AVI).")
    jid=str(uuid.uuid4())[:12]; name=f"{jid}{ext}"; target=UPLOADS/name
    size=0
    with target.open("wb") as f:
        while True:
            chunk=await file.read(1024*1024)
            if not chunk: break
            size+=len(chunk)
            if size>MAX_MB*1024*1024:
                target.unlink(missing_ok=True); raise HTTPException(413,f"File exceeds {MAX_MB} MB limit.")
            f.write(chunk)
    job={"id":jid,"filename":file.filename,"source_file":name,"status":"uploaded","progress":0,"message":"Upload complete. Start AI analysis.","created":datetime.now(timezone.utc).isoformat(),"clips":[],"transcript":{"segments":[]}}
    save_job(job)
    return job
@app.post("/api/analyze/{jid}")
def analyze(jid:str, bg:BackgroundTasks):
    j=get_job(jid)
    if j["status"]=="analyzing": return j
    threading.Thread(target=analyze_worker,args=(jid,),daemon=True).start()
    return update_job(jid,status="analyzing",progress=1,message="Analysis queued…")
@app.get("/api/jobs/{jid}")
def job_status(jid:str): return get_job(jid)
@app.post("/api/render/{jid}/{clip_id}")
def render(jid:str,clip_id:str,ratio:str=Form("9:16"),quality:int=Form(720),burn:bool=Form(True)):
    if ratio not in {"9:16","1:1","16:9"}: raise HTTPException(400,"Invalid aspect ratio")
    if quality not in {480,720,1080}: raise HTTPException(400,"Invalid quality")
    j=get_job(jid); c=next((x for x in j.get("clips",[]) if x["id"]==clip_id),None)
    if not c: raise HTTPException(404,"Clip not found")
    threading.Thread(target=background_render,args=(jid,clip_id,ratio,quality,burn),daemon=True).start()
    return {"ok":True,"message":"Render started"}
@app.post("/api/manual-clip/{jid}")
def manual_clip(jid:str,start:float=Form(...),end:float=Form(...),title:str=Form("My clip")):
    j=get_job(jid)
    if start<0 or end<=start or end>float(j.get("duration",0)): raise HTTPException(400,"Check clip start/end times.")
    clip={"id":str(uuid.uuid4())[:8],"start":start,"end":end,"text":"","score":0,"title":title,"number":len(j["clips"])+1}
    j["clips"].append(clip); save_job(j); return clip
@app.get("/api/search/{jid}")
def search_transcript(jid:str,q:str):
    j=get_job(jid); q=q.strip().lower()
    if not q: return {"results":[]}
    results=[]
    for s in j.get("transcript",{}).get("segments",[]):
        if q in s["text"].lower():
            results.append({"start":s["start"],"end":s["end"],"text":s["text"]})
    return {"results":results[:100]}
@app.post("/api/youtube/auth-url")
def youtube_auth_url():
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError: raise HTTPException(501,"YouTube dependencies not installed.")
    client=os.getenv("YOUTUBE_CLIENT_SECRETS")
    if not client or not Path(client).exists(): raise HTTPException(400,"Set YOUTUBE_CLIENT_SECRETS to your Google OAuth client JSON file.")
    flow=Flow.from_client_secrets_file(client,scopes=["https://www.googleapis.com/auth/youtube.upload"],redirect_uri=os.getenv("YOUTUBE_REDIRECT_URI","http://localhost:8000/api/youtube/callback"))
    url,state=flow.authorization_url(access_type="offline",include_granted_scopes="true",prompt="consent")
    (DATA/"oauth_state.txt").write_text(state)
    return {"url":url,"note":"You must configure an OAuth consent screen and redirect URI in Google Cloud."}
@app.get("/api/youtube/callback")
def youtube_callback(code:str,state:str):
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError: raise HTTPException(501,"YouTube dependencies not installed.")
    statefile=DATA/"oauth_state.txt"
    if not statefile.exists() or statefile.read_text()!=state: raise HTTPException(400,"OAuth state mismatch.")
    client=os.getenv("YOUTUBE_CLIENT_SECRETS")
    flow=Flow.from_client_secrets_file(client,scopes=["https://www.googleapis.com/auth/youtube.upload"],state=state,redirect_uri=os.getenv("YOUTUBE_REDIRECT_URI","http://localhost:8000/api/youtube/callback"))
    flow.fetch_token(code=code)
    (DATA/"youtube_token.json").write_text(flow.credentials.to_json())
    return HTMLResponse("<h2>YouTube connected</h2><p>You can return to ClipAI Pro.</p>")
@app.post("/api/youtube/post/{jid}/{clip_id}")
def youtube_post(jid:str,clip_id:str,title:str=Form(""),description:str=Form(""),privacy:str=Form("private")):
    j=get_job(jid); clip=next((x for x in j["clips"] if x["id"]==clip_id),None)
    if not clip or not clip.get("file"): raise HTTPException(400,"Render this clip first.")
    token=DATA/"youtube_token.json"
    if not token.exists(): raise HTTPException(400,"Connect YouTube first.")
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError: raise HTTPException(501,"YouTube dependencies not installed.")
    creds=Credentials.from_authorized_user_file(str(token),["https://www.googleapis.com/auth/youtube.upload"])
    youtube=build("youtube","v3",credentials=creds)
    body={"snippet":{"title":(title or clip.get("title","ClipAI clip"))[:100],"description":description[:5000],"categoryId":"22","tags":["shorts","ClipAI"]},"status":{"privacyStatus":privacy}}
    req=youtube.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(EXPORTS/clip["file"]),chunksize=-1,resumable=True))
    response=req.execute()
    return {"ok":True,"videoId":response.get("id"),"url":"https://www.youtube.com/watch?v="+response.get("id","")}
