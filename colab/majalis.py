# -*- coding: utf-8 -*-
"""
منظومة «مجالس» — «الاستلام» (المرحلة 2).

بيشتغل على Google Colab (أو على اللابتوب كاحتياطي)، على فولدر «مجالس» في درايف أحمد:

  مجالس/
    الوارد/          ← أحمد بيرمي هنا فولدرات «كاميرا مجالس» (TAF-012_1/ فيها الفيديو والصوت والكود)،
                       أو الملفات نفسها، أو أي فيديو عادي
    الدروس/
      TAF-012/       ← فولدر لكل درس
        TAF-012_1.mp4            الملف الأصلي (ما بيتلمسش أبداً، بيتنقل بس)
        TAF-012_1.m4a            الصوت (من الموبايل، أو بيتطلّع من الفيديو من غير إعادة ضغط)
        TAF-012_1.json           الكود: بيانات التسجيل + كل الدوسات بتوقيتها + سجل التطبيق
        TAF-012_1.backup.m4a     الصوت الاحتياطي (لو موجود جوه الفيديو)
        TAF-012_1.480p.mp4       نسخة صغيرة للمشاهدة والتصحيح
        lesson.json              بطاقة الدرس (بتتعدّل من الموقع)
      يدوي/<اسم الملف>/       ← فيديوهات عادية من غير بيانات (زي اللي اتصوّرت بكاميرا الموبايل)
    النظام/
      index.json       قايمة كل الدروس وحالتها (الموقع بيقراها)
      verses.json      فهرس الآيات والأحاديث: كل آية/حديث في أنهي درس ومن الدقيقة كام لكام
      receive-log.txt  سجل الاستلام

قواعد ثابتة:
- الأصل ما بيتمسحش ولا بيتعدّل أبداً. بيتنقل من «الوارد» لفولدر الدرس وبس.
- كل خطوة ممكن تتعاد: لو Colab فصل في النص، تشغيله تاني بيكمّل اللي ناقص.
"""
import json, os, re, shutil, struct, subprocess, sys, time, datetime, traceback

ROOT = os.environ.get('MAJALIS_ROOT', '/content/drive/MyDrive/مجالس')
INBOX = 'الوارد'
LESSONS = 'الدروس'
MANUAL = 'يدوي'
SYSTEM = 'النظام'
MAKE_PREVIEW = True
NAME_RE = re.compile(r'^(TAF|RYS|TST)-(\d{3,})_(\d+)(?: \(\d+\))?\.mp4$', re.I)
BOOKS = {'TAF': 'التفسير', 'RYS': 'رياض الصالحين', 'TST': 'تجربة الجهاز'}


# ───────────────────────── أدوات ─────────────────────────

def p(*a):
    return os.path.join(ROOT, *a)


def say(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S') + '  ' + msg
    print(msg, flush=True)
    try:
        os.makedirs(p(SYSTEM), exist_ok=True)
        with open(p(SYSTEM, 'receive-log.txt'), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode, r.stdout.decode('utf-8', 'replace'), r.stderr.decode('utf-8', 'replace')


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_bytes(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


_GPU = None
def has_gpu():
    global _GPU
    if _GPU is None:
        _GPU = shutil.which('nvidia-smi') is not None and run(['nvidia-smi'])[0] == 0
    return _GPU


# ───────────────────────── قراية الملف الواحد ─────────────────────────

def read_trailer(path):
    """آخر الملف: صناديق free/MJLS فيها META وTMLN وAUDI وLOGS. بيرجّع {نوع: بايتات} أو None."""
    size = os.path.getsize(path)
    if size < 64:
        return None
    with open(path, 'rb') as f:
        f.seek(size - 32)
        foot = f.read(32)
        if foot[4:8] != b'free' or foot[8:12] != b'MJLS' or foot[12:16] != b'END1':
            return None
        start = struct.unpack('>Q', foot[16:24])[0]
        out, pos = {}, start
        while pos < size - 32:
            f.seek(pos)
            h = f.read(16)
            n = struct.unpack('>I', h[0:4])[0]
            if h[4:8] != b'free' or h[8:12] != b'MJLS' or n < 16:
                break
            out[h[12:16].decode('ascii', 'replace')] = f.read(n - 16)
            pos += n
        out['_start'] = start
        return out


def probe(path):
    """مدة الفيديو، والمقاس، وعدد الصور في الثانية، وفيه صوت ولا لأ. None لو الملف مش بيتقري."""
    code, out, err = run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path])
    if code != 0:
        return None
    d = json.loads(out)
    v = next((s for s in d.get('streams', []) if s.get('codec_type') == 'video'), None)
    a = next((s for s in d.get('streams', []) if s.get('codec_type') == 'audio'), None)
    fps = 0.0
    if v and v.get('avg_frame_rate', '0/0') != '0/0':
        n, m = v['avg_frame_rate'].split('/')
        fps = round(float(n) / float(m), 2) if float(m) else 0.0
    return {
        'durMs': int(float(d.get('format', {}).get('duration', 0)) * 1000),
        'w': v.get('width') if v else 0, 'h': v.get('height') if v else 0, 'fps': fps,
        'vcodec': v.get('codec_name') if v else '', 'acodec': a.get('codec_name') if a else '',
        'audio': bool(a), 'bitrate': int(d.get('format', {}).get('bit_rate', 0) or 0),
    }


def load_code(ldir, base):
    """ملف الكود (TAF-012_1.json): {"meta":…, "timeline":[…], "log":"…"}."""
    return read_json(os.path.join(ldir, base + '.json'))


def load_events(ldir, base):
    c = load_code(ldir, base)
    return (c or {}).get('timeline') or []


def timeline_events(raw):
    evs = []
    for line in raw.decode('utf-8', 'replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evs.append(json.loads(line))
        except Exception:
            pass
    return evs


# ───────────────────────── فهرس الآيات والأحاديث ─────────────────────────

def segments(evs, book, dur_ms):
    """من التوقيتات: كل آية (أو حديث) ظهرت إمتى لحد إمتى في التسجيل ده (بالثواني)."""
    marks = []
    for e in evs:
        t = e.get('t')
        if not isinstance(t, (int, float)) or t < 0:
            continue
        if book == 'TAF' and 's' in e and 'a' in e:
            marks.append((t, '%d:%d' % (int(e['s']), int(e['a'])), e.get('sc')))
        elif book == 'RYS' and 'b' in e and 'i' in e:
            marks.append((t, 'b%d:i%d' % (int(e['b']), int(e['i'])), e.get('sc'), e.get('h') or ''))
    marks.sort(key=lambda m: m[0])
    segs = []
    for k, m in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else dur_ms
        if end <= m[0]:
            continue
        if segs and segs[-1]['key'] == m[1] and abs(segs[-1]['to'] * 1000 - m[0]) < 1:
            segs[-1]['to'] = round(end / 1000, 2)          # نفس الآية (تغيير مشهد بس): نكمّل نفس المقطع
            continue
        s = {'key': m[1], 'from': round(m[0] / 1000, 2), 'to': round(end / 1000, 2)}
        if book == 'RYS' and len(m) > 3 and m[3]:
            s['h'] = m[3]
        segs.append(s)
    return segs


# ───────────────────────── تسجيل واحد ─────────────────────────

def ffmpeg_ok(cmd, out):
    code, _, err = run(cmd)
    if code != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        if os.path.exists(out):
            os.remove(out)
        say('   ⚠️ ffmpeg: ' + err.strip().splitlines()[-1] if err.strip() else '   ⚠️ ffmpeg فشل')
        return False
    return True


def process_recording(ldir, fname):
    """بيطلّع كل حاجة ناقصة لتسجيل واحد جوه فولدر الدرس. ينفع يتشغّل أكتر من مرة."""
    src = os.path.join(ldir, fname)
    base = fname[:-4]
    info = {'file': fname, 'bytes': os.path.getsize(src)}
    tr = read_trailer(src)
    code_path = os.path.join(ldir, base + '.json')
    if tr:
        info['trailer'] = True
        info['videoBytes'] = tr['_start']
        # الكود: لو ملف الـ json ماوصلش جنب الفيديو، نطلّعه من النسخة اللي جوه الفيديو
        if not os.path.exists(code_path) and ('META' in tr or 'TMLN' in tr):
            meta = json.loads(tr.get('META', b'{}') or b'{}')
            evs = timeline_events(tr.get('TMLN', b''))
            write_json(code_path, {'majalis': 1, 'meta': meta, 'timeline': evs, 'log': tr.get('LOGS', b'').decode('utf-8', 'replace'), 'from': 'inside-video'})
        bk = os.path.join(ldir, base + '.backup.m4a')
        if 'AUDI' in tr and len(tr['AUDI']) > 1000 and not os.path.exists(bk):
            aac = os.path.join(ldir, base + '.backup.aac.tmp')
            write_bytes(aac, tr['AUDI'])
            ffmpeg_ok(['ffmpeg', '-y', '-v', 'error', '-f', 'aac', '-i', aac, '-c:a', 'copy', '-bsf:a', 'aac_adtstoasc', '-movflags', '+faststart', bk], bk)
            os.remove(aac)
        info['backupAudio'] = os.path.exists(bk)
    else:
        info['trailer'] = False
    info['code'] = os.path.exists(code_path)

    pr = probe(src)
    if not pr:
        info['ok'] = False
        info['problem'] = 'الفيديو مش بيتقري (ممكن يكون اتقطع). محتاج تصليح — الأصل محفوظ زي ما هو.'
        say('   ❌ ' + info['problem'])
        return info
    info.update(pr)
    info['ok'] = True

    m4a = os.path.join(ldir, base + '.m4a')
    if pr['audio'] and not os.path.exists(m4a):
        ffmpeg_ok(['ffmpeg', '-y', '-v', 'error', '-i', src, '-vn', '-c:a', 'copy', '-movflags', '+faststart', m4a], m4a)
    info['m4a'] = os.path.exists(m4a)

    prev = os.path.join(ldir, base + '.480p.mp4')
    if MAKE_PREVIEW and not os.path.exists(prev):
        say('   … نسخة المشاهدة الصغيرة (480p)%s' % (' بكارت الشاشة' if has_gpu() else ''))
        tmp = prev + '.part.mp4'
        venc = ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '30'] if has_gpu() else ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28']
        ok = ffmpeg_ok(['ffmpeg', '-y', '-v', 'error', '-i', src, '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'scale=-2:480']
                       + venc + ['-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', tmp], tmp)
        if not ok and has_gpu():          # لو كارت الشاشة رفض: بالطريقة العادية
            ok = ffmpeg_ok(['ffmpeg', '-y', '-v', 'error', '-i', src, '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'scale=-2:480',
                            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', tmp], tmp)
        if ok:
            os.replace(tmp, prev)
    info['preview'] = os.path.exists(prev)
    return info


# ───────────────────────── بطاقة الدرس ─────────────────────────

def hijri(d):
    try:
        from hijridate import Gregorian
        h = Gregorian(d.year, d.month, d.day).to_hijri()
        return '%d-%02d-%02d' % (h.year, h.month, h.day)
    except Exception:
        return ''


def update_card(ldir, code, recs):
    card = read_json(os.path.join(ldir, 'lesson.json'), {}) or {}
    book = code.split('-')[0]
    card.setdefault('code', code)
    card['book'] = book
    card.setdefault('majlis', int(code.split('-')[1]))
    card.setdefault('status', 'وصل')
    card.setdefault('notes', '')
    recs = sorted(recs, key=lambda r: int(re.search(r'_(\d+)', r['file']).group(1)) if re.search(r'_(\d+)', r['file']) else 0)
    card['recordings'] = recs
    card['durMs'] = sum(r.get('durMs', 0) for r in recs if r.get('ok'))
    card['problems'] = [r['file'] + ': ' + r['problem'] for r in recs if r.get('problem')]
    # من بيانات أول تسجيل: الشيخ، والتاريخ، ومكان البداية
    meta = ((load_code(ldir, recs[0]['file'][:-4]) or {}).get('meta') or {}) if recs else {}
    inf = (meta or {}).get('info', {}) or {}
    if meta and 'startedWall' in meta and 'date' not in card:
        d = datetime.datetime.fromtimestamp(meta['startedWall'] / 1000)
        card['date'] = d.strftime('%Y-%m-%d')
        card['hijri'] = hijri(d)
    for k_src, k_dst in (('name', 'sheikh'), ('title', 'honorific'), ('org', 'org')):
        if inf.get(k_src) and k_dst not in card:
            card[k_dst] = inf[k_src]
    if book == 'TAF' and inf.get('surahName') and 'surahName' not in card:
        card['surah'] = inf.get('surah'); card['surahName'] = inf['surahName']
    if book == 'RYS' and inf.get('babLabel') and 'bab' not in card:
        card['bab'] = inf['babLabel']
    # من التوقيتات: أول وآخر آية/حديث في الدرس
    keys = []
    for r in recs:
        evs = load_events(ldir, r['file'][:-4])
        if evs:
            segs = segments(evs, book, r.get('durMs') or 0)
            keys += [s for s in segs if s['to'] - s['from'] >= 1]
    if keys:
        card['range'] = {'from': keys[0]['key'], 'to': keys[-1]['key'], 'count': len({s['key'] for s in keys})}
    card['updatedAt'] = time.strftime('%Y-%m-%d %H:%M')
    write_json(os.path.join(ldir, 'lesson.json'), card)
    return card


# ───────────────────────── الاستلام ─────────────────────────

def setup():
    for d in (INBOX, LESSONS, os.path.join(LESSONS, MANUAL), SYSTEM):
        os.makedirs(p(d), exist_ok=True)


def lesson_dir_for(fname):
    m = NAME_RE.match(fname)
    if not m:
        return None, None
    code = '%s-%s' % (m.group(1).upper(), m.group(2))
    return code, p(LESSONS, code)


VIDEO_EXT = ('.mp4', '.mov', '.m4v', '.mkv')


def receive_inbox():
    """كل فيديو في «الوارد» (أو في فولدر جواه)، ومعاه ملفاته (نفس الاسم: ‎.json و‎.m4a)، بيتنقل لفولدر الدرس."""
    found = []
    for dirpath, dirnames, filenames in os.walk(p(INBOX)):
        for f in sorted(filenames):
            if f.lower().endswith(VIDEO_EXT) and not f.startswith('.') and not f.endswith('.480p.mp4'):
                found.append((dirpath, f))
    if not found:
        say('«الوارد» فاضي.')
    touched = set()
    for dirpath, f in found:
        src = os.path.join(dirpath, f)
        # ملف لسه بيترفع؟ نستنى لما حجمه يثبت
        s1 = os.path.getsize(src); time.sleep(2); s2 = os.path.getsize(src)
        if s1 != s2:
            say('⏳ %s لسه بيترفع — هيتاخد المرة الجاية' % f)
            continue
        stem = os.path.splitext(f)[0]
        code, ldir = lesson_dir_for(f)
        if not code:
            tr = read_trailer(src)
            fn = json.loads(tr.get('META', b'{}') or b'{}').get('file') if tr else None
            code, ldir = lesson_dir_for(fn) if fn else (None, None)
            if not code:
                # فيديو عادي (من كاميرا الموبايل مثلاً): فولدر لوحده لحد ما يتعمله بيانات من الموقع
                ldir = p(LESSONS, MANUAL, stem); code = MANUAL + '/' + stem
        os.makedirs(ldir, exist_ok=True)
        sibs = [x for x in os.listdir(dirpath) if x != f and x.startswith(stem + '.') and not x.lower().endswith(VIDEO_EXT)]
        dst = os.path.join(ldir, f)
        if os.path.exists(dst):
            if os.path.getsize(dst) == os.path.getsize(src):
                say('↺ %s موجود قبل كده في %s — اتساب في «الوارد» زي ما هو' % (f, code))
                continue
            stem2 = stem + '.dup-' + time.strftime('%Y%m%d%H%M%S')
            dst = os.path.join(ldir, stem2 + os.path.splitext(f)[1])
            sibs_dst = {x: os.path.join(ldir, stem2 + x[len(stem):]) for x in sibs}
        else:
            sibs_dst = {x: os.path.join(ldir, x) for x in sibs}
        shutil.move(src, dst)               # نقل بس — الأصل ما بيتغيّرش
        for x, xd in sibs_dst.items():
            if not os.path.exists(xd):
                shutil.move(os.path.join(dirpath, x), xd)
        say('📥 %s%s ← %s' % (f, (' + ' + '، '.join(sorted(s[len(stem):] for s in sibs))) if sibs else '', code))
        touched.add(ldir)
        # فولدر التسجيل في «الوارد» فضي؟ نشيله (لو فيه أي حاجة تانية بيفضل زي ما هو)
        if os.path.normpath(dirpath) != os.path.normpath(p(INBOX)):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    return touched


def refresh_lesson(ldir):
    code = os.path.relpath(ldir, p(LESSONS))
    vids = sorted(f for f in os.listdir(ldir) if f.lower().endswith(('.mp4', '.mov', '.m4v', '.mkv'))
                  and not f.endswith('.480p.mp4') and not f.endswith('.part.mp4'))
    if not vids:
        return None
    say('— %s' % code)
    old = {r['file']: r for r in (read_json(os.path.join(ldir, 'lesson.json'), {}) or {}).get('recordings', [])}
    recs = []
    for v in vids:
        try:
            r = process_recording(ldir, v)
        except Exception as e:
            r = dict(old.get(v, {}), file=v, ok=False, problem='خطأ وقت الاستلام: %s' % e)
            say('   ❌ ' + traceback.format_exc().strip().splitlines()[-1])
        recs.append(r)
        say('   %s %s — %s دقيقة، %sx%s، %s صورة/ث%s%s' % (
            '✓' if r.get('ok') else '✗', v, round(r.get('durMs', 0) / 60000, 1), r.get('w', '?'), r.get('h', '?'), r.get('fps', '?'),
            '' if r.get('trailer') else ' (فيديو عادي من غير توقيتات)', '، فيه صوت احتياطي' if r.get('backupAudio') else ''))
    if code.startswith(MANUAL + os.sep) or code.startswith(MANUAL + '/'):
        card = read_json(os.path.join(ldir, 'lesson.json'), {}) or {}
        card.update({'code': code, 'book': '', 'status': card.get('status', 'محتاج بيانات'), 'recordings': recs,
                     'durMs': sum(r.get('durMs', 0) for r in recs if r.get('ok')), 'manual': True,
                     'updatedAt': time.strftime('%Y-%m-%d %H:%M')})
        write_json(os.path.join(ldir, 'lesson.json'), card)
        return card
    return update_card(ldir, code, recs)


def all_lesson_dirs():
    out = []
    for d in sorted(os.listdir(p(LESSONS))):
        full = p(LESSONS, d)
        if not os.path.isdir(full):
            continue
        if d == MANUAL:
            out += [os.path.join(full, x) for x in sorted(os.listdir(full)) if os.path.isdir(os.path.join(full, x))]
        else:
            out.append(full)
    return out


def rebuild_indexes():
    """index.json (قايمة الدروس) وverses.json (فهرس الآيات والأحاديث) — بيتبنوا من الأول كل مرة من ملفات الدروس."""
    lessons, verses = [], {'TAF': {}, 'RYS': {}}
    for ldir in all_lesson_dirs():
        card = read_json(os.path.join(ldir, 'lesson.json'))
        if not card:
            continue
        lessons.append({k: card.get(k) for k in ('code', 'book', 'majlis', 'date', 'hijri', 'status', 'durMs', 'range',
                                                 'surahName', 'bab', 'sheikh', 'manual', 'problems', 'title', 'reviewed')})
        book = card.get('book')
        if book not in verses:
            continue
        for r in card.get('recordings', []):
            evs = load_events(ldir, r['file'][:-4]) if r.get('ok') else []
            if not evs:
                continue
            for s in segments(evs, book, r.get('durMs') or 0):
                if s['to'] - s['from'] < 1:
                    continue
                e = {'lesson': card['code'], 'file': r['file'], 'from': s['from'], 'to': s['to']}
                if 'h' in s:
                    e['h'] = s['h']
                verses[book].setdefault(s['key'], []).append(e)
    lessons.sort(key=lambda x: (x.get('book') or 'ZZZ', x.get('majlis') or 0, x.get('code') or ''))
    write_json(p(SYSTEM, 'index.json'), {'updatedAt': time.strftime('%Y-%m-%d %H:%M'), 'lessons': lessons})
    write_json(p(SYSTEM, 'verses.json'), {'updatedAt': time.strftime('%Y-%m-%d %H:%M'), 'verses': verses})
    n = sum(len(v) for v in verses['TAF'].values()) + sum(len(v) for v in verses['RYS'].values())
    say('📚 الفهرس: %d درس، و%d مقطع آية/حديث.' % (len(lessons), n))


def receive(all_lessons=False):
    """الاستلام: ملفات «الوارد» ← فولدرات الدروس، وبعدين الفهارس.
    all_lessons=True: يراجع كل الدروس القديمة كمان (لو حاجة اتمسحت أو اتضافت)."""
    if not os.path.isdir(ROOT):
        os.makedirs(ROOT, exist_ok=True)
    setup()
    say('==== استلام — %s ====' % time.strftime('%Y-%m-%d %H:%M'))
    touched = receive_inbox()
    dirs = all_lesson_dirs() if all_lessons else sorted(touched)
    if not all_lessons:
        # أي درس ناقصه حاجة من مرة فاتت (Colab فصل في النص) يكمّل
        for d in all_lesson_dirs():
            card = read_json(os.path.join(d, 'lesson.json'))
            vids = [f for f in os.listdir(d) if f.lower().endswith('.mp4') and not f.endswith('.480p.mp4')]
            if d not in touched and (not card or len(card.get('recordings', [])) != len(vids)
                                     or any(MAKE_PREVIEW and r.get('ok') and not r.get('preview') for r in card.get('recordings', []))):
                dirs.append(d)
    for d in dirs:
        try:
            refresh_lesson(d)
        except Exception:
            say('❌ ' + d + ': ' + traceback.format_exc().strip().splitlines()[-1])
    rebuild_indexes()
    say('✓ خلص.')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        ROOT = sys.argv[1]
    receive(all_lessons='--all' in sys.argv)
