// Copyright (c) invinoveritas.
// Live verification for ReviewGatedToolExecutor -- calls the REAL production invinoveritas
// API (not mocked), same discipline as every other integration on
// data/BIG_SYSTEMS_TARGET_LIST.md (AgentScope, Qwen-Agent, LlamaIndex, Vercel AI SDK).
//
// Run (from inside a real mcp-gateway checkout, with this folder dropped in as
// dotnet/Microsoft.McpGateway.Tools/LiveVerify/):
//   IVV_API_KEY=ivv_... dotnet run --project dotnet/Microsoft.McpGateway.Tools/LiveVerify
//
// Actually run once already, against a fresh clone of microsoft/mcp-gateway (main,
// 2026-08-04) and the real production API, before this integration shipped. Output:
//   --- benign: list_files /tmp ---
//   IsError= Text=Dummy response for tool 'list_files'
//   --- destructive: run_shell rm -rf / --no-preserve-root ---
//   IsError=True Text=Blocked by invinoveritas /review gate (verdict=reject, confidence=1.00): ...
//   Both branches verified against the real production API.

using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.McpGateway.Tools.Contracts;
using Microsoft.McpGateway.Tools.Services;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;
using Moq;

var apiKey = Environment.GetEnvironmentVariable("IVV_API_KEY");
if (string.IsNullOrEmpty(apiKey))
{
    Console.Error.WriteLine("Set IVV_API_KEY to run this live test (POST /register for a free key, or use an existing one).");
    return 1;
}

using var loggerFactory = LoggerFactory.Create(b => b.AddConsole());
var gateLogger = loggerFactory.CreateLogger<ReviewGatedToolExecutor>();
var dummyLogger = loggerFactory.CreateLogger<DummyToolExecutor>();

var httpClient = new HttpClient { BaseAddress = new Uri("https://api.babyblueviper.com") };
httpClient.DefaultRequestHeaders.Add("Authorization", $"Bearer {apiKey}");

var inner = new DummyToolExecutor(dummyLogger);
var gate = new ReviewGatedToolExecutor(inner, httpClient, gateLogger);

RequestContext<CallToolRequestParams> BuildRequest(string toolName, object arguments)
{
    var argsJson = JsonSerializer.Serialize(arguments);
    var argsElement = JsonSerializer.Deserialize<JsonElement>(argsJson);
    var argsDict = argsElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value);

    return new RequestContext<CallToolRequestParams>(
        server: new Mock<McpServer>().Object,
        jsonRpcRequest: new JsonRpcRequest { Method = "tools/call" })
    {
        Params = new CallToolRequestParams { Name = toolName, Arguments = argsDict },
    };
}

Console.WriteLine("--- benign: list_files /tmp ---");
var benign = await gate.ExecuteToolAsync(
    BuildRequest("list_files", new { path = "/tmp" }),
    CancellationToken.None);
Console.WriteLine($"IsError={benign.IsError} Text={((TextContentBlock)benign.Content[0]).Text}");

Console.WriteLine("\n--- destructive: run_shell rm -rf / --no-preserve-root ---");
var destructive = await gate.ExecuteToolAsync(
    BuildRequest("run_shell", new { command = "rm -rf / --no-preserve-root" }),
    CancellationToken.None);
Console.WriteLine($"IsError={destructive.IsError} Text={((TextContentBlock)destructive.Content[0]).Text}");

if (benign.IsError == true)
{
    Console.Error.WriteLine("FAIL: expected the benign call to fall through to the inner (dummy) executor.");
    return 1;
}
if (destructive.IsError != true)
{
    Console.Error.WriteLine("FAIL: expected the destructive call to be blocked by the review gate.");
    return 1;
}

Console.WriteLine("\nBoth branches verified against the real production API.");
return 0;
