# Lentera Riset

Pemantau riset NLP untuk **bahasa berdaya sumber rendah, bahasa daerah Indonesia, dan bahasa Austronesia lainnya**. Setiap hari, situs ini mengambil makalah baru dari arXiv, ACL Anthology, dan OpenAlex (jurnal seperti IEEE), mengurutkannya menurut relevansi dan keramaian, lalu membuat ringkasan dalam **bahasa Inggris dan bahasa Indonesia** secara berdampingan sebagai pembanding.

Terinspirasi oleh [Emergent Mind](https://www.emergentmind.com/), tetapi seluruhnya memakai layanan gratis.

Situs: <https://feliksmakarios.github.io/lentera-riset/>

## Fitur

- Pengambilan makalah harian dari tiga sumber:
  - **arXiv** (cs.CL, cs.AI, cs.LG, cs.SD, eess.AS), lewat umpan RSS harian dan API pencarian per topik.
  - **ACL Anthology**, lewat data XML terbuka di GitHub ([acl-org/acl-anthology](https://github.com/acl-org/acl-anthology)). Volume prosiding yang baru masuk diperiksa setiap hari.
  - **OpenAlex**, untuk jurnal dan konferensi lain (misalnya IEEE Transactions). Perlu kunci API gratis.
- Makalah yang sama dari beberapa sumber (misalnya versi arXiv dan versi ACL) digabung menjadi satu.
- Skor relevansi per topik: bahasa Indonesia dan daerah, Austronesia lainnya, Asia Tenggara, berdaya sumber rendah, serta multibahasa.
- Sinyal keramaian dari Hugging Face Papers, Hacker News, GitHub, dan jumlah sitasi Semantic Scholar.
- Ringkasan dwibahasa dari Gemini yang **membaca isi lengkap makalah** (PDF akses terbuka), dengan enam bagian: latar belakang masalah, penelitian terkait, kontribusi dan kebaruan, metode, hasil dan pembahasan, serta penelitian selanjutnya. Jika PDF tidak tersedia, ringkasan dibuat dari abstrak.
- TL;DR dua kalimat dari abstrak di bawah nama penulis, mirip TL;DR Semantic Scholar.
- Istilah teknis yang lazim dipertahankan dalam bahasa Inggris dan dicetak miring, disertai glosarium berbahasa Indonesia.
- **Beranda** dengan dua tab: "Sedang ramai" (10 makalah teramai) dan "Terbaru" (7 makalah per halaman). Keduanya diperbarui setiap hari.
- **Kolom pencarian berdasarkan makna** di bagian atas setiap halaman, seperti di Hugging Face dan Semantic Scholar. Pertanyaan dalam bahasa Indonesia atau Inggris dicocokkan dengan makalah berdasarkan kedekatan makna, bukan hanya kesamaan kata. Hasilnya bisa disaring menurut rentang waktu, topik, dan bahasa. Jika Worker pencarian belum aktif, hasil memakai kecocokan kata kunci.
- **Halaman Makalah** bergaya halaman Models di Hugging Face: panel kiri berisi saringan **Tugas** (misalnya terjemahan mesin, pengenalan ucapan, analisis sentimen), **Topik**, dan **Bahasa**, masing-masing dengan kolom untuk mencari pilihan. Bahasa dikenali dari judul dan abstrak serta dari daftar bahasa yang dikaji menurut ringkasan Gemini; tugas dikenali dari kata kunci di `[[tasks]]`.
- **Makalah serupa** di setiap halaman makalah, berdasarkan kedekatan makna judul dan abstrak.
- Umpan RSS di `feed.xml`.

## Cara kerja

```
arXiv, ACL Anthology, OpenAlex ──► penilaian relevansi ──► sinyal keramaian ──► PDF + ringkasan Gemini ──► vektor makna ──► data/ ──► situs statis
                                    (config/topics.toml)   (HF, HN, GitHub, S2)   (Inggris + Indonesia)      (embedding Gemini)           (GitHub Pages)

Pengunjung ──► halaman Cari ──► Cloudflare Worker ──► embedding Gemini untuk pertanyaan ──► dibandingkan dengan vektor makalah di peramban
```

Semuanya berjalan di GitHub Actions setiap hari pukul 06.00 WIB. Data disimpan di `data/papers.json` dan `data/embeddings.json` di dalam repositori, jadi tidak perlu basis data. Makalah yang sudah diringkas tidak diringkas ulang, kecuali abstraknya berubah. Begitu pula vektornya.

Pencarian semantik bekerja begini: setiap makalah diubah menjadi vektor makna (embedding) dari judul dan abstraknya saat alur kerja harian berjalan. Saat pengunjung mencari, pertanyaannya diubah menjadi vektor oleh Cloudflare Worker kecil dengan model yang sama, lalu peramban mengurutkan makalah menurut kemiripan kosinus. Kunci Gemini hanya tersimpan di Worker, tidak pernah dikirim ke peramban.

## Penyiapan (sekali saja)

1. **Buat kunci API Gemini** gratis di <https://aistudio.google.com/apikey>.
2. Di repositori ini, buka **Settings > Secrets and variables > Actions > New repository secret**. Isi nama `GEMINI_API_KEY` dan tempel kuncinya.
3. Buka **Settings > Pages**, lalu pada bagian **Build and deployment > Source** pilih **GitHub Actions**.
4. Buka tab **Actions**, pilih alur kerja **Perbarui data dan terbitkan situs**, lalu klik **Run workflow** untuk menjalankan pertama kali.

Tanpa `GEMINI_API_KEY`, situs tetap berjalan dan menampilkan abstrak asli tanpa ringkasan.

5. **Opsional, untuk jumlah sitasi yang lebih andal:** minta kunci API Semantic Scholar gratis lewat <https://www.semanticscholar.org/product/api#api-key-form>, lalu simpan sebagai secret `SEMANTIC_SCHOLAR_API_KEY`. Tanpa kunci, permintaan memakai jatah bersama yang kadang ditolak saat ramai.
6. **Opsional, untuk jurnal seperti IEEE:** buat kunci API OpenAlex gratis di <https://openalex.org/settings/api>, lalu simpan sebagai secret `OPENALEX_API_KEY`. Tanpa kunci ini, sumber OpenAlex dilewati dan situs tetap berjalan dengan arXiv dan ACL Anthology.

### Pencarian semantik (Cloudflare Worker)

Vektor makalah dibuat otomatis oleh alur kerja harian memakai `GEMINI_API_KEY`. Supaya pertanyaan pengunjung juga bisa diubah menjadi vektor, terbitkan Worker di `worker/` sekali saja:

1. Buat akun Cloudflare gratis di <https://dash.cloudflare.com/sign-up>, lalu buka menu **Workers & Pages** sekali. Langkah ini menyiapkan subdomain `workers.dev` untuk akun Anda.
2. Buka **My Profile > API Tokens > Create Token**, pilih templat **Edit Cloudflare Workers**, lalu buat tokennya. Simpan token sebagai secret repositori `CLOUDFLARE_API_TOKEN`.
3. Salin **Account ID** (ada di kolom kanan halaman **Workers & Pages**, atau di alamat dasbor setelah `dash.cloudflare.com/`). Simpan sebagai secret repositori `CLOUDFLARE_ACCOUNT_ID`.
4. Di tab **Actions**, jalankan **Terbitkan Worker pencarian semantik**. Ringkasan hasilnya menampilkan alamat Worker, misalnya `https://lentera-riset.nama-anda.workers.dev`. `GEMINI_API_KEY` ikut disimpan sebagai secret Worker secara otomatis.
5. Buka **Settings > Secrets and variables > Actions**, tab **Variables**, lalu buat variabel `WORKER_URL` berisi alamat tadi.
6. Jalankan **Perbarui data dan terbitkan situs**. Halaman **Cari** kini memakai pencarian semantik.

Tanpa langkah ini, halaman Cari tetap berjalan dengan kecocokan kata kunci, dan daftar makalah serupa tetap muncul.

## Memperluas cakupan

Semua topik dan kata kunci ada di [`config/topics.toml`](config/topics.toml). Untuk menambah topik baru (misalnya bahasa Papua, atau seluruh NLP), tambahkan blok `[[topics]]` baru. Kode tidak perlu diubah.

- `weight`: seberapa besar satu kata kunci menambah skor.
- `query = false`: kata kunci hanya dipakai untuk penilaian, tidak untuk mencari di arXiv. Cocok untuk kata yang terlalu umum seperti "multilingual".
- `min_relevance` di bagian `[ranking]`: ambang minimum agar makalah disimpan.

Daftar tugas untuk saringan di halaman Makalah ada di blok `[[tasks]]`, dan daftar bahasa ada di blok `[[languages]]` pada berkas yang sama. Setiap bahasa punya `aliases`, yaitu nama-nama yang dicari di judul dan abstrak. Bahasa lain yang dicatat Gemini sebagai bahasa yang dikaji otomatis mendapat halaman jika muncul di minimal dua makalah (`auto_language_min_papers` di bagian `[search]`).

## Menjalankan secara lokal

Hanya butuh Python 3.11 ke atas. Tidak ada pustaka tambahan.

```bash
python -m unittest discover -s tests -t .      # pengujian
node --test worker/index.test.mjs              # pengujian Worker (Node 20 ke atas)
export GEMINI_API_KEY=...                      # opsional
python -m lentera update                       # ambil data (lihat --help untuk opsi)
python -m lentera build --out _site            # bangun situs
python -m http.server -d _site 8000            # buka http://localhost:8000
```

## Batasan kuota gratis

- **Gemini**: kuota harian terbatas, jadi maksimal 40 ringkasan baru per hari (bisa diatur di `[summaries]`). Pada versi gratis, Google boleh memakai data permintaan untuk meningkatkan layanannya. Yang dikirim hanya makalah akses terbuka yang memang sudah publik.
- **OpenAlex**: 100.000 kredit per hari dengan kunci gratis; satu pencarian memakai 10 kredit, dan situs ini hanya memakai beberapa pencarian per hari.
- **Embedding Gemini**: kuotanya terpisah dari kuota ringkasan. Makalah dikirim per 25 dengan jeda 20 detik. Pada jalankan pertama, sekitar 600 makalah membutuhkan kurang lebih 8 menit; selanjutnya hanya makalah baru.
- **Cloudflare Workers**: 100.000 permintaan per hari pada paket gratis. Worker membatasi 30 pencarian per menit untuk setiap alamat IP dan hanya melayani halaman Lentera Riset.
- **Makalah berbayar** (misalnya sebagian besar makalah IEEE) tidak punya PDF akses terbuka, jadi ringkasannya dibuat dari abstrak.
- **arXiv**: jeda minimal 3 detik antarpermintaan sudah diterapkan. Saat bebannya tinggi, API arXiv kadang menolak dengan kode 406. Sistem akan mencoba ulang beberapa kali, dan jika tetap ditolak, makalah hari itu tetap masuk lewat umpan RSS.
- **GitHub Actions dan Pages**: gratis tanpa batas untuk repositori publik.
- **X (Twitter)** tidak dipakai karena API-nya berbayar. **Reddit** belum dipakai karena mewajibkan OAuth.

## Rencana berikutnya

- Tahap 3: tanya jawab tentang makalah, memakai Worker yang sama dan Gemini.

## Atribusi

Thank you to arXiv for use of its open access interoperability. Proyek ini tidak berafiliasi dengan arXiv, dan hak cipta setiap makalah tetap milik penulisnya.
