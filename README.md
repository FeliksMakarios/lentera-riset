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
- Halaman depan dengan urutan "Sedang ramai" dan "Terbaru", saring topik, dan pencarian.
- Umpan RSS di `feed.xml`.

## Cara kerja

```
arXiv, ACL Anthology, OpenAlex ──► penilaian relevansi ──► sinyal keramaian ──► PDF + ringkasan Gemini ──► data/papers.json ──► situs statis
                                    (config/topics.toml)   (HF, HN, GitHub, S2)   (Inggris + Indonesia)                          (GitHub Pages)
```

Semuanya berjalan di GitHub Actions setiap hari pukul 06.00 WIB. Data disimpan di `data/papers.json` di dalam repositori, jadi tidak perlu basis data. Makalah yang sudah diringkas tidak diringkas ulang, kecuali abstraknya berubah.

## Penyiapan (sekali saja)

1. **Buat kunci API Gemini** gratis di <https://aistudio.google.com/apikey>.
2. Di repositori ini, buka **Settings > Secrets and variables > Actions > New repository secret**. Isi nama `GEMINI_API_KEY` dan tempel kuncinya.
3. Buka **Settings > Pages**, lalu pada bagian **Build and deployment > Source** pilih **GitHub Actions**.
4. Buka tab **Actions**, pilih alur kerja **Perbarui data dan terbitkan situs**, lalu klik **Run workflow** untuk menjalankan pertama kali.

Tanpa `GEMINI_API_KEY`, situs tetap berjalan dan menampilkan abstrak asli tanpa ringkasan.

5. **Opsional, untuk jurnal seperti IEEE:** buat kunci API OpenAlex gratis di <https://openalex.org/settings/api>, lalu simpan sebagai secret `OPENALEX_API_KEY`. Tanpa kunci ini, sumber OpenAlex dilewati dan situs tetap berjalan dengan arXiv dan ACL Anthology.

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

- **Gemini**: kuota harian terbatas, jadi maksimal 40 ringkasan baru per hari (bisa diatur di `[summaries]`). Pada versi gratis, Google boleh memakai data permintaan untuk meningkatkan layanannya. Yang dikirim hanya makalah akses terbuka yang memang sudah publik.
- **OpenAlex**: 100.000 kredit per hari dengan kunci gratis; satu pencarian memakai 10 kredit, dan situs ini hanya memakai beberapa pencarian per hari.
- **Makalah berbayar** (misalnya sebagian besar makalah IEEE) tidak punya PDF akses terbuka, jadi ringkasannya dibuat dari abstrak.
- **arXiv**: jeda minimal 3 detik antarpermintaan sudah diterapkan. Saat bebannya tinggi, API arXiv kadang menolak dengan kode 406. Sistem akan mencoba ulang beberapa kali, dan jika tetap ditolak, makalah hari itu tetap masuk lewat umpan RSS.
- **GitHub Actions dan Pages**: gratis tanpa batas untuk repositori publik.
- **X (Twitter)** tidak dipakai karena API-nya berbayar. **Reddit** belum dipakai karena mewajibkan OAuth.

## Rencana berikutnya

- Tahap 2: pencarian semantik dan halaman per topik atau per bahasa.
- Tahap 3: tanya jawab tentang makalah (Cloudflare Workers dan Gemini).

## Atribusi

Thank you to arXiv for use of its open access interoperability. Proyek ini tidak berafiliasi dengan arXiv, dan hak cipta setiap makalah tetap milik penulisnya.
