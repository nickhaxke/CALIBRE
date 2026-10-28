"""Create an original, redistributable EPUB fixture for the desktop import test."""
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

TITLE = 'The Open Horizon: Friday Research Edition'


def create_book(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cover = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900"><rect width="600" height="900" fill="#183c34"/><circle cx="420" cy="620" r="250" fill="#82946e"/><circle cx="420" cy="620" r="190" fill="none" stroke="#d8c69c" stroke-width="2"/><text x="60" y="95" fill="#d8c69c" font-size="17" font-family="sans-serif" letter-spacing="4">INSTITUTIONAL EDITIONS</text><g fill="#fff9e9" font-family="serif" font-size="65"><text x="60" y="245">The Open</text><text x="60" y="325">Horizon</text></g><text x="60" y="390" fill="#d8c69c" font-size="22" font-family="sans-serif">A FIELD GUIDE TO DISCOVERY</text><text x="60" y="825" fill="#fff9e9" font-size="18" font-family="sans-serif">INSTITUTIONAL LIBRARY TEAM</text></svg>'
    chapters = [
        ('An invitation to curiosity', 'Every discovery starts with a question. A library holds more than answers: it offers new ways to ask. This original demonstration book celebrates research, thoughtful reading, and the shared work of learning.'),
        ('Following an idea', 'Start with a topic that matters to you. Explore a subject, notice the authors who return to it, and compare the perspectives you find. Good research is a conversation across time and disciplines.'),
        ('Making room for possibility', 'Keep a record of what you notice. Read slowly, return to difficult passages, and share your questions with others. A new perspective can begin on an ordinary afternoon with an open book.'),
    ]
    from qt.core import QByteArray, QImage, QPainter, QSvgRenderer, Qt
    from calibre.utils.img import image_to_data
    image = QImage(600, 900, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(cover.encode('utf-8'))).render(painter)
    painter.end()
    raster_cover = image_to_data(image)
    with ZipFile(destination, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', compress_type=ZIP_STORED)
        z.writestr('META-INF/container.xml', '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>', compress_type=ZIP_DEFLATED)
        manifest = '<item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        manifest += ''.join(f'<item id="c{i}" href="chapter{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(1, 4))
        spine = ''.join(f'<itemref idref="c{i}"/>' for i in range(1, 4))
        z.writestr('OEBPS/content.opf', f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:uuid:31f42014-2b51-4ee7-961c-202610300001</dc:identifier><dc:title>{TITLE}</dc:title><dc:creator>Institutional Library Team</dc:creator><dc:language>en</dc:language><dc:publisher>Institutional Editions</dc:publisher><dc:date>2026-10-28</dc:date><dc:subject>Research</dc:subject><dc:subject>Digital Libraries</dc:subject><dc:description>An original field guide to curiosity, research, and learning together. Created for the institutional library demonstration.</dc:description><meta property="dcterms:modified">2026-10-28T00:00:00Z</meta><meta name="cover" content="cover"/></metadata><manifest>{manifest}</manifest><spine>{spine}</spine></package>', compress_type=ZIP_DEFLATED)
        z.writestr('OEBPS/cover.svg', cover, compress_type=ZIP_DEFLATED)
        z.writestr('OEBPS/cover.jpg', raster_cover, compress_type=ZIP_DEFLATED)
        links = ''.join(f'<li><a href="chapter{i}.xhtml">{title}</a></li>' for i, (title, _) in enumerate(chapters, 1))
        z.writestr('OEBPS/nav.xhtml', f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><h1>Contents</h1><ol>{links}</ol></nav></body></html>', compress_type=ZIP_DEFLATED)
        for i, (title, text) in enumerate(chapters, 1):
            z.writestr(f'OEBPS/chapter{i}.xhtml', f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title><style>body{{font-family:serif;line-height:1.7;padding:2em}}h1{{font-weight:normal}}</style></head><body><h1>{title}</h1><p>{text}</p><p>This volume is an original demonstration fixture. It contains no client or production material.</p></body></html>', compress_type=ZIP_DEFLATED)
    return destination


if __name__ == '__main__':
    print(create_book(Path(__file__).resolve().parents[1] / '.demo/ingest/open-horizon.epub'))
