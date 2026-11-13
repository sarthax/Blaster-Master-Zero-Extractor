"""Inti Asset Explorer — read-only Windows-friendly Tkinter browser.

Tk widgets and PhotoImage are created only on the UI thread. Archive reads,
texture decoding and gallery generation run on workers and post results to a
queue that is drained by after(). No game content is bundled.
"""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import queue
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, ImageDraw

from .inti import Source, Entry, Preview, decode_preview, discover_sources
from .inventory import scan_path, write_reports


class AssetBrowser(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Inti Asset Explorer · Blaster Master Zero')
        self.geometry('1350x840')
        self.minsize(980, 620)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.events: queue.Queue = queue.Queue()
        self.sources: list[Source] = []
        self.source: Source | None = None
        self.entry: Entry | None = None
        self.preview: Preview | None = None
        self.entry_bytes: bytes | None = None
        self.preview_token = 0
        self.gallery_token = 0
        self.photo = None
        self.gallery_photos = []
        self.gallery_cells = {}
        self.current_image = None
        self.current_dir = None
        self._build()
        self.after(80, self._drain)
        self.protocol('WM_DELETE_WINDOW', self._close)

    def _build(self):
        self.configure(bg='#f2f4f8')
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(side='top', fill='x')
        ttk.Label(top, text='INTI ASSET EXPLORER', font=('Segoe UI', 16, 'bold')).pack(side='left', padx=(0, 18))
        ttk.Button(top, text='Open game folder…', command=self.open_folder).pack(side='left', padx=3)
        ttk.Button(top, text='Open archive / resource…', command=self.open_file).pack(side='left', padx=3)
        ttk.Button(top, text='Export inventory…', command=self.export_inventory).pack(side='right', padx=3)
        ttk.Button(top, text='Export current PNG…', command=self.export_png).pack(side='right', padx=3)
        ttk.Button(top, text='Export raw…', command=self.export_raw).pack(side='right', padx=3)
        ttk.Button(top, text='Extract archive…', command=self.export_archive).pack(side='right', padx=3)

        body = ttk.PanedWindow(self, orient='horizontal')
        body.pack(fill='both', expand=True, padx=10, pady=(0, 5))
        side = ttk.Frame(body, padding=4)
        center = ttk.Frame(body, padding=4)
        right = ttk.Frame(body, padding=4)
        body.add(side, weight=1)
        body.add(center, weight=2)
        body.add(right, weight=4)

        ttk.Label(side, text='ARCHIVES', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=6)
        self.archives = ttk.Treeview(side, show='tree', selectmode='browse', height=15)
        self.archives.pack(fill='both', expand=True)
        self.archives.bind('<<TreeviewSelect>>', self.on_archive)
        self.archive_note = ttk.Label(side, text='Choose a directory containing .irlst + .irarc pairs',
                                      wraplength=210, justify='left')
        self.archive_note.pack(fill='x', pady=10)

        ttk.Label(center, text='RESOURCES', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=6)
        findbar = ttk.Frame(center)
        findbar.pack(fill='x', pady=(0, 6))
        self.search = tk.StringVar()
        searchbox = ttk.Entry(findbar, textvariable=self.search)
        searchbox.pack(side='left', expand=True, fill='x')
        self.search.trace_add('write', lambda *_: self.filter_resources())
        self.resource_count = ttk.Label(center, text='0 resources')
        self.resource_count.pack(anchor='w', pady=(0, 5))
        reswrap = ttk.Frame(center)
        reswrap.pack(fill='both', expand=True)
        self.resources = ttk.Treeview(reswrap, columns=('kind','size'), show='tree headings', selectmode='browse')
        self.resources.heading('#0', text='Resource ID')
        self.resources.heading('kind', text='Kind')
        self.resources.heading('size', text='Packed')
        self.resources.column('#0', width=140, minwidth=105)
        self.resources.column('kind', width=53, minwidth=50, anchor='center')
        self.resources.column('size', width=78, minwidth=62, anchor='e')
        vscroll = ttk.Scrollbar(reswrap, orient='vertical', command=self.resources.yview)
        self.resources.configure(yscrollcommand=vscroll.set)
        self.resources.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')
        self.resources.bind('<<TreeviewSelect>>', self.on_resource)
        self.resources.bind('<Control-c>', self.copy_resource_id)
        ttk.Label(center, text='Search by hexadecimal ID, decimal ID, or type',
                  foreground='#667085').pack(anchor='w', pady=(5, 0))

        ttk.Label(right, text='ASSET PREVIEW', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=6)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill='both', expand=True)
        self.texture_tab = ttk.Frame(self.tabs)
        self.frame_tab = ttk.Frame(self.tabs)
        self.details_tab = ttk.Frame(self.tabs)
        self.gallery_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.texture_tab, text='Texture / palette')
        self.tabs.add(self.frame_tab, text='Sprite frame (experimental)')
        self.tabs.add(self.details_tab, text='Resource details')
        self.tabs.add(self.gallery_tab, text='Gallery')

        texbar = ttk.Frame(self.texture_tab, padding=5)
        texbar.pack(fill='x')
        ttk.Label(texbar, text='Variant').pack(side='left')
        self.variant_var = tk.StringVar()
        self.variant_select = ttk.Combobox(texbar, textvariable=self.variant_var, state='readonly', width=20)
        self.variant_select.pack(side='left', padx=(7, 20))
        self.variant_select.bind('<<ComboboxSelected>>', lambda _e: self._show_current())
        ttk.Label(texbar, text='Zoom').pack(side='left')
        self.zoom = tk.StringVar(value='Fit')
        zoomselect = ttk.Combobox(texbar, textvariable=self.zoom, state='readonly',
                                  values=['Fit','1x','2x','4x','8x'], width=7)
        zoomselect.pack(side='left', padx=6)
        zoomselect.bind('<<ComboboxSelected>>', lambda _e: self._show_current())
        self.tex_canvas, self.tex_area = self._make_canvas(self.texture_tab)
        self.tex_canvas.bind('<Configure>', lambda _e: self._show_current())
        self.texture_meta = ttk.Label(self.texture_tab, text='Select a resource to preview', padding=7)
        self.texture_meta.pack(anchor='w')

        framebar = ttk.Frame(self.frame_tab, padding=5)
        framebar.pack(fill='x')
        ttk.Button(framebar, text='◀', width=3, command=lambda: self._change_frame(-1)).pack(side='left')
        self.frame_index = tk.IntVar(value=0)
        self.frame_spin = tk.Spinbox(framebar, from_=0, to=0, width=7,
                                     textvariable=self.frame_index, command=self._show_frame)
        self.frame_spin.pack(side='left', padx=5)
        self.frame_spin.bind('<Return>', lambda _e: self._show_frame())
        ttk.Button(framebar, text='▶', width=3, command=lambda: self._change_frame(1)).pack(side='left')
        self.frame_total = ttk.Label(framebar, text='No frames')
        self.frame_total.pack(side='left', padx=10)
        self.frame_canvas, self.frame_area = self._make_canvas(self.frame_tab)
        self.frame_canvas.bind('<Configure>', lambda _e: self._show_frame())
        self.frame_meta = ttk.Label(self.frame_tab,
                                    text='Frame rendering supports axis-aligned PTGT quads only.', padding=7)
        self.frame_meta.pack(anchor='w')

        self.details = tk.Text(self.details_tab, wrap='word', font=('Consolas', 10),
                               background='#fbfbfb', borderwidth=0, state='disabled')
        self.details.pack(fill='both', expand=True, padx=8, pady=8)

        gallerybar = ttk.Frame(self.gallery_tab, padding=6)
        gallerybar.pack(fill='x')
        ttk.Button(gallerybar, text='Generate archive thumbnails', command=self.build_gallery).pack(side='left')
        self.gallery_status = ttk.Label(gallerybar, text='On demand · does not export assets')
        self.gallery_status.pack(side='left', padx=10)
        self.gallery_canvas = tk.Canvas(self.gallery_tab, borderwidth=0, highlightthickness=0, bg='#e9edf2')
        gallery_scroll = ttk.Scrollbar(self.gallery_tab, orient='vertical', command=self.gallery_canvas.yview)
        self.gallery_canvas.configure(yscrollcommand=gallery_scroll.set)
        gallery_scroll.pack(side='right', fill='y')
        self.gallery_canvas.pack(side='left', fill='both', expand=True)
        self.gallery_inner = ttk.Frame(self.gallery_canvas, padding=8)
        self.gallery_canvas.create_window((0,0), window=self.gallery_inner, anchor='nw')
        self.gallery_inner.bind('<Configure>', lambda _e: self.gallery_canvas.configure(
            scrollregion=self.gallery_canvas.bbox('all')))
        self.gallery_canvas.bind('<MouseWheel>', lambda e: self.gallery_canvas.yview_scroll(
            -1 if e.delta > 0 else 1, 'units'))

        self.status = tk.StringVar(value='Open a Blaster Master Zero data/resarc folder to begin.')
        ttk.Label(self, textvariable=self.status, relief='sunken', anchor='w', padding=6).pack(fill='x', side='bottom')

    def _make_canvas(self, parent):
        area = ttk.Frame(parent)
        area.pack(fill='both', expand=True)
        canvas = tk.Canvas(area, background='#d0d4d9', highlightthickness=0)
        sy = ttk.Scrollbar(area, orient='vertical', command=canvas.yview)
        sx = ttk.Scrollbar(area, orient='horizontal', command=canvas.xview)
        canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        canvas.pack(side='left', fill='both', expand=True)
        return canvas, area

    def _background(self, job, done):
        def worker():
            try:
                result = job()
                self.events.put((done, result, None))
            except Exception as exc:
                self.events.put((done, None, str(exc)))
        self.executor.submit(worker)

    def _drain(self):
        try:
            while True:
                callback, result, error = self.events.get_nowait()
                callback(result, error)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(80, self._drain)

    def _close(self):
        self.gallery_token += 1
        self.preview_token += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    def open_folder(self):
        directory = filedialog.askdirectory(title='Select game data / resarc directory')
        if directory:
            self.load_path(Path(directory))

    def open_file(self):
        path = filedialog.askopenfilename(title='Choose an archive or extracted resource', filetypes=[
            ('Inti Creates resources', '*.irlst *.irarc *.17'), ('All files', '*.*')])
        if path:
            self.load_path(Path(path))

    def load_path(self, path):
        self.status.set(f'Scanning {path}…')
        self.current_dir = path
        self.preview_token += 1
        self.gallery_token += 1
        self._background(lambda: discover_sources(path), self._loaded_sources)

    def _loaded_sources(self, result, error):
        if error:
            self.status.set(f'Open failed: {error}')
            messagebox.showerror('Cannot open source', error)
            return
        self.sources = result
        self.archives.delete(*self.archives.get_children())
        for i, source in enumerate(self.sources):
            self.archives.insert('', 'end', iid=str(i), text=f'{source.label} ({len(source.entries):,})')
        self.status.set(f'Found {len(self.sources)} archive / loose resource source(s)')
        if result:
            self.archives.selection_set('0')
            self.on_archive()

    def on_archive(self, _event=None):
        sel = self.archives.selection()
        if not sel:
            return
        source = self.sources[int(sel[0])]
        if source is self.source:
            return
        self.source = source
        self.entry = None
        self.preview = None
        self.entry_bytes = None
        self.preview_token += 1
        self.gallery_token += 1
        self.search.set('')
        self._clear_gallery()
        self.archive_note.config(text=f'{source.path}\n\n{len(source.entries)} entries\n'
                                 + ('Loose decoded files' if source.is_loose else f'Archive: {source.archive.name}'))
        self.filter_resources()
        self._details_text(f'Source: {source.label}\nEntries: {len(source.entries)}\nPath: {source.path}')
        self.status.set(f'{source.label}: select a resource ID or build thumbnails')

    def filter_resources(self):
        self.resources.delete(*self.resources.get_children())
        if not self.source:
            return
        needle = self.search.get().strip().lower().replace('0x','')
        matching = []
        for e in self.source.entries:
            if not needle or needle in f'{e.resource_id:08x}' or needle in str(e.resource_id) or needle in f'{e.kind:x}':
                matching.append(e)
                self.resources.insert('', 'end', iid=str(e.ordinal), text=f'{e.resource_id:08X}',
                                      values=(f'{e.kind:#04x}', f'{e.packed_size:,}'))
        self.resource_count.config(text=f'{len(matching):,} of {len(self.source.entries):,} resources')

    def on_resource(self, _event=None):
        selection = self.resources.selection()
        if not selection or self.source is None:
            return
        entry = self.source.entries[int(selection[0])]
        if self.entry is entry:
            return
        self.entry = entry
        self.preview = None
        self.entry_bytes = None
        self.preview_token += 1
        token = self.preview_token
        source = self.source
        self.status.set(f'Loading resource 0x{entry.resource_id:08X}…')
        self.texture_meta.configure(text='Decoding…')
        self._background(lambda: (source.get_data(entry),),
                         lambda result, error: self._loaded_bytes(token, entry, result, error))

    def _loaded_bytes(self, token, entry, result, error):
        if token != self.preview_token or self.entry is not entry:
            return
        if error:
            self._decode_error(entry, error)
            return
        data = result[0]
        self.entry_bytes = data
        self._background(lambda: decode_preview(data),
                         lambda result, error: self._loaded_preview(token, entry, data, result, error))

    def _decode_error(self, entry, error):
        self.status.set(f'Error loading {entry.name}: {error}')
        self.texture_meta.configure(text=f'Unable to decode: {error}')
        self._details_text(f'Resource: {entry.name}\nRead error: {error}')

    def _loaded_preview(self, token, entry, data, result, error):
        if token != self.preview_token or self.entry is not entry:
            return
        if error:
            # Retain raw bytes for export even when the decoder cannot parse it.
            self.preview = Preview('Unsupported / decode error', [], [], 0, 0, [], error)
        else:
            self.preview = result
        p = self.preview
        variants = [f'Palette {i + 1}' if p.palette_count else f'Texture {i + 1}'
                    for i in range(len(p.images))]
        self.variant_select.configure(values=variants)
        self.variant_select.current(0) if variants else self.variant_var.set('None')
        self.frame_index.set(0)
        self.frame_spin.configure(to=max(0, len(p.frames)-1))
        self.frame_total.configure(text=f'/ {max(0, len(p.frames)-1)} · {len(p.frames)} frames')
        self._details_text(f'Archive: {self.source.label}\n'
                           f'ID: 0x{entry.resource_id:08X} ({entry.resource_id})\n'
                           f'Index: {entry.ordinal}\nType: 0x{entry.kind:02X}\n'
                           f'Packed bytes: {entry.packed_size:,}\n'
                           f'Unpacked bytes: {len(data):,}\n'
                           f'Offset: 0x{entry.offset:X}\n'
                           f'Classification: {p.classification}\n'
                           f'Sections: {", ".join(p.sections) or "none"}\n'
                           f'Textures: {p.tex_count}\nPalettes: {p.palette_count}\n'
                           f'Frame records: {len(p.frames)}\n'
                           f'Notes: {p.note}\n\n'
                           f'Original data is read-only. Sprite frames may not reproduce the engine precisely.')
        self._show_current()
        self._show_frame()
        self.status.set(f'{entry.name} · {p.classification} · {len(p.images)} variant(s) · {len(p.frames)} frames')

    def _details_text(self, value):
        self.details.configure(state='normal')
        self.details.delete('1.0','end')
        self.details.insert('1.0', value)
        self.details.configure(state='disabled')

    def _variant_index(self):
        if not self.preview or not self.preview.images:
            return 0
        return max(0, min(self.variant_select.current(), len(self.preview.images)-1))

    @staticmethod
    def _checkerboard(img):
        bg = Image.new('RGBA', img.size, '#dadde2')
        d = ImageDraw.Draw(bg)
        for y in range(0, img.height, 16):
            for x in range(0, img.width, 16):
                if (x // 16 + y // 16) % 2:
                    d.rectangle((x, y, x+15, y+15), fill='#f7f8fa')
        return Image.alpha_composite(bg, img.convert('RGBA')).convert('RGB')

    def _draw(self, canvas, image):
        canvas.delete('all')
        if image is None:
            canvas.create_text(max(180, canvas.winfo_width()//2), max(130, canvas.winfo_height()//2),
                               text='No preview for this resource', fill='#565f6b')
            if canvas is self.tex_canvas:
                self.photo = None
            return
        iw, ih = image.size
        zoom = self.zoom.get()
        if zoom == 'Fit':
            availw = max(100, canvas.winfo_width()-30)
            availh = max(100, canvas.winfo_height()-30)
            factor = min(availw/iw, availh/ih, 8)
        else:
            factor = int(zoom[:-1])
        factor = max(0.05, min(factor, 8, 4096/iw, 4096/ih))
        size = (max(1, int(round(iw*factor))), max(1, int(round(ih*factor))))
        scaled = image.resize(size, Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(self._checkerboard(scaled), master=self)
        canvas._preview_photo = photo  # retain during other tab changes
        canvas.configure(scrollregion=(0,0,max(canvas.winfo_width(),size[0]),
                                        max(canvas.winfo_height(),size[1])))
        x = max(0,(canvas.winfo_width()-size[0])//2)
        y = max(0,(canvas.winfo_height()-size[1])//2)
        canvas.create_image(x, y, anchor='nw', image=photo)

    def _show_current(self):
        if not self.preview or not self.preview.images:
            self.current_image = None
            self._draw(self.tex_canvas, None)
            self.texture_meta.configure(text='No supported texture')
            return
        im = self.preview.images[self._variant_index()]
        self.current_image = im
        self._draw(self.tex_canvas, im)
        self.texture_meta.configure(text=f'{im.width} × {im.height} RGBA  ·  {self.preview.classification}')
        self._show_frame()

    def _show_frame(self):
        if not self.preview or not self.preview.frames:
            self._draw(self.frame_canvas, None)
            return
        try:
            index = int(self.frame_index.get())
        except (ValueError, tk.TclError):
            index = 0
        index = max(0, min(index, len(self.preview.frames)-1))
        self.frame_index.set(index)
        image = self.preview.frame_at(index, self._variant_index())
        self._draw(self.frame_canvas, image)
        if image:
            self.frame_meta.configure(text=f'Frame {index} · {image.width} × {image.height} · experimental reconstruction')
        else:
            self.frame_meta.configure(text=f'Frame {index}: no renderable axis-aligned quads')

    def _change_frame(self, delta):
        if self.preview and self.preview.frames:
            self.frame_index.set(max(0, min(len(self.preview.frames)-1, self.frame_index.get()+delta)))
            self._show_frame()

    def copy_resource_id(self, _event=None):
        if self.entry:
            self.clipboard_clear()
            self.clipboard_append(f'{self.entry.resource_id:08X}')

    def export_png(self):
        if not self.preview:
            messagebox.showinfo('Export PNG', 'Select a graphical resource first.')
            return
        im = self.preview.frame_at(self.frame_index.get(), self._variant_index()) if (
            self.tabs.index(self.tabs.select()) == 1 and self.preview.frames) else self.current_image
        if im is None:
            messagebox.showinfo('Export PNG', 'No decoded image is available in this view.')
            return
        name = (f'{self.entry.resource_id:08X}_frame_{self.frame_index.get():04d}.png'
                if self.tabs.index(self.tabs.select()) == 1 else
                f'{self.entry.resource_id:08X}_{self._variant_index():02d}.png')
        dest = filedialog.asksaveasfilename(title='Export PNG', defaultextension='.png',
                                            initialfile=name, filetypes=[('PNG', '*.png')])
        if dest:
            im.save(dest)
            self.status.set(f'Saved PNG: {dest}')

    def export_raw(self):
        if not self.entry or not self.source:
            messagebox.showinfo('Export raw', 'Select a resource first.')
            return
        dest = filedialog.asksaveasfilename(title='Export decompressed resource',
                                            initialfile=self.entry.export_name)
        if not dest:
            return
        data = self.entry_bytes if self.entry_bytes is not None else self.source.get_data(self.entry)
        Path(dest).write_bytes(data)
        self.status.set(f'Saved resource: {dest}')

    def export_inventory(self):
        """Scan all pairs in the chosen folder, even ones the browser skipped."""
        if self.current_dir is None:
            messagebox.showinfo('Export inventory', 'Open an archive or game folder first.')
            return
        dest = filedialog.asksaveasfilename(
            title='Save metadata inventory JSON and CSV',
            defaultextension='.json', initialfile='inti_inventory.json',
            filetypes=[('JSON report', '*.json')])
        if not dest:
            return
        target = Path(dest)
        if (target.exists() or target.with_suffix('.csv').exists()) and not messagebox.askyesno(
                'Overwrite existing reports?', 'The JSON or CSV report already exists. Replace both?'):
            return
        scan_target = self.current_dir
        self.status.set(f'Scanning archive metadata from {scan_target}…')

        def job():
            report = scan_path(scan_target)
            paths = write_reports(report, target)
            return report['summary'], paths

        def done(result, error):
            if error:
                self.status.set(f'Inventory failed: {error}')
                messagebox.showerror('Inventory failed', error)
                return
            summary, (json_path, csv_path) = result
            counts = summary['statuses']
            failures = counts.get('read_error', 0) + counts.get('parse_error', 0)
            self.status.set(f"Inventory: {summary['resources']} resources, "
                            f"{failures} resource errors, {summary['pair_errors']} pair errors")
            messagebox.showinfo('Inventory completed',
                                f"Archives: {summary['sources']}\nResources: {summary['resources']}\n"
                                f"Read/parse errors: {failures}\nPair errors: {summary['pair_errors']}\n\n"
                                f"JSON: {json_path}\nCSV: {csv_path}")
        self._background(job, done)

    def export_archive(self):
        if not self.source:
            messagebox.showinfo('Extract archive', 'Select an archive first.')
            return
        folder = filedialog.askdirectory(title='Select output directory for extracted resources')
        if not folder:
            return
        source = self.source
        output = Path(folder)/source.label.replace(':','_')
        self.status.set(f'Extracting {len(source.entries)} resources…')
        def job():
            output.mkdir(parents=True, exist_ok=True)
            rows=[]; extracted=skipped=failed=0
            for e in source.entries:
                dst=output/e.export_name
                try:
                    if dst.exists():
                        skipped+=1; status='skipped_exists'; size=dst.stat().st_size
                    else:
                        payload=source.get_data(e)
                        dst.write_bytes(payload)
                        extracted+=1; status='extracted';size=len(payload)
                except Exception as exc:
                    failed+=1; status=f'error: {exc}';size=0
                rows.append((e.ordinal,f'0x{e.resource_id:08X}',f'0x{e.kind:02X}',
                             e.packed_size,size,e.export_name,status))
            with (output/'manifest.csv').open('w',newline='',encoding='utf-8') as f:
                w=csv.writer(f);w.writerow(['index','resource_id','kind','packed_bytes',
                                             'unpacked_bytes','file','status']);w.writerows(rows)
            return extracted,skipped,failed,output
        def done(result,error):
            if error:
                self.status.set(f'Extraction failed: {error}')
                messagebox.showerror('Extraction',error)
                return
            n,s,e,d=result
            self.status.set(f'Extracted {n}, skipped existing {s}, errors {e} → {d}')
            messagebox.showinfo('Extraction complete',f'{n} extracted, {s} skipped, {e} errors\n{d}')
        self._background(job, done)

    def _clear_gallery(self):
        for w in self.gallery_inner.winfo_children():
            w.destroy()
        self.gallery_photos.clear()
        self.gallery_cells.clear()
        self.gallery_status.configure(text='On demand · does not export assets')

    def build_gallery(self):
        if not self.source:
            return
        self.gallery_token += 1
        token = self.gallery_token
        source = self.source
        self._clear_gallery()
        self.tabs.select(self.gallery_tab)
        self.gallery_status.configure(text=f'Generating thumbnails for {len(source.entries)} resources…')
        def job():
            thumbnails = []
            for i,e in enumerate(source.entries):
                if token != self.gallery_token:  # cancellation checked by worker
                    break
                try:
                    preview = decode_preview(source.get_data(e))
                    if preview.images:
                        im = preview.images[0].copy()
                        im.thumbnail((110,92),Image.Resampling.NEAREST)
                        thumbnails.append((e.ordinal, im, preview.classification))
                except Exception:
                    continue  # Unsupported entries remain inspectable via resource list.
            return thumbnails
        self._background(job, lambda result,error: self._loaded_gallery(token, source, result, error))

    def _loaded_gallery(self, token, source, results, error):
        if token != self.gallery_token or self.source is not source:
            return
        if error:
            self.gallery_status.configure(text=f'Gallery failed: {error}')
            return
        for j,(ordinal,im,classification) in enumerate(results):
            cell = ttk.Frame(self.gallery_inner, padding=5, relief='ridge')
            cell.grid(row=j//5, column=j%5, padx=4, pady=4, sticky='n')
            photo=ImageTk.PhotoImage(self._checkerboard(im),master=self)
            self.gallery_photos.append(photo)
            thumbnail=tk.Label(cell,image=photo,cursor='hand2',borderwidth=0)
            thumbnail.pack()
            label=ttk.Label(cell,text=f'{source.entries[ordinal].resource_id:08X}',font=('Consolas',9))
            label.pack()
            desc=ttk.Label(cell,text=classification,font=('Segoe UI',8),foreground='#667085')
            desc.pack()
            for widget in (thumbnail,label,desc,cell):
                widget.bind('<Button-1>', lambda _e, i=ordinal: self._gallery_jump(i))
        self.gallery_status.configure(text=f'{len(results)} graphic resources / {len(source.entries)} total')

    def _gallery_jump(self, ordinal):
        if not self.source:
            return
        self.tabs.select(self.texture_tab)
        self.search.set('')
        iid=str(ordinal)
        self.resources.selection_set(iid)
        self.resources.see(iid)
        self.on_resource()


def main():
    try:
        AssetBrowser().mainloop()
    except tk.TclError as exc:
        raise SystemExit(f'Unable to start desktop GUI: {exc}') from exc


if __name__ == '__main__':
    main()
