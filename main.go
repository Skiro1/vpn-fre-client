package main

import (
	"embed"
	"log"

	"github.com/skkvpn/free-vpn-new/internal/vpn"
	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
)

//go:embed all:frontend/dist
var assets embed.FS

//go:embed build/windows/icon.ico
var iconBytes []byte

func main() {
	vpn.InitLogger()

	settings, _ := vpn.LoadSettings()
	vpn.Log.SetEnabled(settings.LogEnabled)

	app := application.New(application.Options{
		Name:        "Free VPN",
		Description: "Free VPN Client using Cloudflare WARP",
		Services: []application.Service{
			application.NewService(NewVpnService()),
		},
		Assets: application.AssetOptions{
			Handler: application.AssetFileServerFS(assets),
		},
		Mac: application.MacOptions{
			ApplicationShouldTerminateAfterLastWindowClosed: false,
		},
	})

	window := app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title:         "Free VPN Client",
		Width:         420,
		Height:        760,
		MinWidth:      420,
		MinHeight:     760,
		MaxWidth:      420,
		MaxHeight:     760,
		DisableResize: true,
		BackgroundColour: application.NewRGB(0, 0, 0),
		URL:  "/",
	})

	window.RegisterHook(events.Common.WindowClosing, func(e *application.WindowEvent) {
		window.Hide()
		e.Cancel()
	})

	tray := app.SystemTray.New()
	tray.SetIcon(iconBytes)
	tray.SetTooltip("SKKVPN")

	tray.OnClick(func() {
		if window.IsVisible() {
			window.Hide()
		} else {
			window.Show()
			window.Focus()
		}
	})

	menu := app.NewMenu()
	menu.Add("Show/Hide").OnClick(func(ctx *application.Context) {
		if window.IsVisible() {
			window.Hide()
		} else {
			window.Show()
			window.Focus()
		}
	})
	menu.AddSeparator()
	menu.Add("Quit").OnClick(func(ctx *application.Context) {
		app.Quit()
	})
	tray.SetMenu(menu)

	if err := app.Run(); err != nil {
		log.Fatal(err)
	}
}
