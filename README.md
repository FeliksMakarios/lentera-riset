# Lentera Riset

Pemantau riset NLP untuk **bahasa berdaya sumber rendah, bahasa daerah Indonesia, dan bahasa Austronesia lainnya**. Setiap hari, situs ini mengambil makalah baru dari arXiv, mengurutkannya menurut relevansi dan keramaian, lalu membuat ringkasan dalam **bahasa Inggris dan bahasa Indonesia** secara berdampingan sebagai pembanding.

Terinspirasi oleh [Emergent Mind](https://www.emergentmind.com/), tetapi seluruhnya memakai layanan gratis.

Situs: <https://feliksmakarios.github.io/lentera-riset/>

## Fitur tahap 1

- Pengambilan makalah harian dari arXiv (cs.CL, cs.AI, cs.LG, cs.SD, eess.AS) berdasarkan kata kunci topik.
- Skor relevansi per topik: bahasa Indonesia dan daerah, Austronesia lainnya, Asia Tenggara, berdaya sumber rendah, serta multibahasa.
- Sinyal keramaian dari Hugging Face Papers, Hacker News, GitHub, dan jumlah sitasi Semantic Scholar.
- Ringkasan dwibahasa dari Gemini. Istilah teknis yang lazim dipertahankan dalam bahasa Inggris dan dicetak miring, disertai glosarium berbahasa Indonesia.
- Halaman depan dengan urutan "Sedang ramai" dan "Terbaru", saring topik, dan pencarian.
- Umpan RSS di `feed.xml`.

## Cara kerja

```
arXiv API ──► penilaian relevansi ──► sinyal keramaian ──► ringkasan Gemini ──► data/papers.json ──► situs statis
                (config/topics.toml)   (HF, HN, GitHub, S2)   (Inggris + Indonesia)                     (GitHub Pages)
```

Semuanya berjalan di GitHub Actions setiap hari pukul 06.00 WIB. Data disimpan di `data/papers.json` di dalam repositori, jadi tidak perlu basis data. Makalah yang sudah diringkas tidak diringkas ulang, kecuali abstraknya berubah.

## Penyiapan (sekali saja)

1. **Buat kunci API Gemini** gratis di <https://aistudio.google.com/apikey>.
2. Di repositori ini, buka **Settings > Secrets and variables > Actions > New repository secret**. Isi nama `GEMINI_API_KEY` dan tempel kuncinya.
3. Buka **Settings > Pages**, lalu pada bagian **Build and deployment > Source** pilih **GitHub Actions**.
4. Buka tab **Actions**, pilih alur kerja **Perbarui data dan terbitkan situs**, lalu klik **Run workflow** untuk menjalankan pertama kali.

Tanpa `GEMINI_API_KEY`, situs tetap berjalan dan menampilkan abstrak asli tanpa ringkasan.

## Memperluas cakupan

Semua topik dan kata kunci ada di [`config/topics.toml`](config/topics.toml). Untuk menambah topik baru (misalnya bahasa Papua, atau seluruh NLP), tambahkan blok `[[topics]]` baru. Kode tidak perlu diubah.

- `weight`: seberapa besar satu kata kunci menambah skor.
- `query = false`: kata kunci hanya dipakai untuk penilaian, tidak untuk mencari di arXiv. Cocok untuk kata yang terlalu umum seperti "multilingual".
- `min_relevance` di bagian `[ranking]`: ambang minimum agar makalah disimpan.

## Menjalankan secara lokal

Hanya butuh Python 3.11 ke atas. Tidak ada pustaka tambahan.

```bash
python -m unittest discover -s tests -t .      # pengujian
export GEMINI_API_KEY=...                      # opsional
python -m lentera update                       # ambil data (lihat --help untuk opsi)
python -m lentera build --out _site            # bangun situs
python -m http.server -d _site 8000            # buka http://localhost:8000
```

## Batasan kuota gratis

- **Gemini**: kuota harian terbatas, jadi maksimal 25 ringkasan baru per hari (bisa diatur di `[summaries]`). Pada versi gratis, Google boleh memakai data permintaan untuk meningkatkan layanannya. Karena yang dikirim hanya judul dan abstrak makalah publik, hal ini tidak menjadi masalah.
- **arXiv**: jeda minimal 3 detik antarpermintaan sudah diterapkan.
- **GitHub Actions dan Pages**: gratis tanpa batas untuk repositori publik.
- **X (Twitter)** tidak dipakai karena API-nya berbayar. **Reddit** belum dipakai karena mewajibkan OAuth.

## Rencana berikutnya

- Tahap 2: pencarian semantik dan halaman per topik atau per bahasa.
- Tahap 3: tanya jawab tentang makalah (Cloudflare Workers dan Gemini).

## Atribusi

Thank you to arXiv for use of its open access interoperability. Proyek ini tidak berafiliasi dengan arXiv, dan hak cipta setiap makalah tetap milik penulisnya.
