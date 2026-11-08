/* Standalone classic Worker: deliberately outside web.assets_backend. */
const READER_OPTIONS = {
    formats: ["Code39", "Code128", "EAN-13", "EAN-8", "UPC-A", "UPC-E",
        "ITF", "Codabar", "Code93", "QRCode", "DataMatrix"],
    tryHarder: true,
    tryRotate: false,
    maxNumberOfSymbols: 8,
};
const ready = (async () => {
    importScripts("zxing_reader.iife.js");
    await ZXingWASM.prepareZXingModule({
        overrides: {
            locateFile: (path, prefix) => path.endsWith(".wasm")
                ? new URL("zxing_reader.wasm", self.location.href).href : prefix + path,
        },
        fireImmediately: true,
    });
})();
ready.then(() => self.postMessage({ type: "ready" }), (error) => {
    self.postMessage({ type: "error", error: String(error) });
});
self.onmessage = async ({ data }) => {
    let bitmap;
    try {
        await ready;
        let image = data.imageData;
        bitmap = data.imageBitmap;
        if (bitmap) {
            const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
            const context = canvas.getContext("2d");
            context.drawImage(bitmap, 0, 0);
            image = context.getImageData(0, 0, canvas.width, canvas.height);
        }
        const results = await ZXingWASM.readBarcodes(image, READER_OPTIONS);
        self.postMessage({ id: data.id, results: results.map(({ text, position }) => ({ text, position })) });
    } catch (error) {
        self.postMessage({ id: data.id, results: [], error: String(error) });
    } finally {
        bitmap?.close();
    }
};
