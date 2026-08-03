// Abstraction over the on-node LLM runtime (docs/09 §6).
// Swap runtime = write a new class; call sites stay the same.
using System.Text.Json;

namespace NodeAgent;

public record GenParams(int MaxTokens = 512, double Temperature = 0.7);

public record LlmResult(
    string Text,
    int? TokensIn,
    int? TokensOut,
    double PromptMs,
    double PredictMs,
    bool TokensEstimated = false);

public interface ILlmRunner
{
    string? ActiveModelId { get; }
    string? ActiveModelSha256 { get; }
    string? ActiveRuntimeId { get; }
    long ActiveModelGeneration { get; }
    bool IsRuntimeReady { get; }

    Task<bool> EnsureReadyAsync(RoomConfig cfg, IProgress<double>? progress);
    Task<LlmResult> GenerateAsync(string prompt, GenParams p, CancellationToken ct,
        Func<string, Task>? onDelta = null);
    Task ShutdownAsync();
}

/// <summary>Subset of room_config from POST /join (ADR-005 / ADR-006 pins).</summary>
public sealed class RoomConfig
{
    public string? ModelId { get; init; }
    public string? ModelUrl { get; init; }
    public string? ModelSha256 { get; init; }
    public string? ModelFilename { get; init; }
    public string? RuntimeUrl { get; init; }
    public string? RuntimeSha256 { get; init; }
    public string? RuntimeId { get; init; }
    public long ModelGeneration { get; init; }
    public string? LlamaServerExeSha256 { get; init; }
    public string? LlamaServerImplDllSha256 { get; init; }
    public IReadOnlyList<string> AllowedDomains { get; init; } = Array.Empty<string>();

    /// <summary>Local GGUF filename from room_config or URL basename.</summary>
    public string ResolveModelFilename()
    {
        string? raw = null;
        if (!string.IsNullOrWhiteSpace(ModelFilename))
            raw = ModelFilename;
        else if (!string.IsNullOrWhiteSpace(ModelUrl))
        {
            try
            {
                raw = Path.GetFileName(new Uri(ModelUrl!).AbsolutePath);
            }
            catch { /* fall through */ }
        }
        var name = Path.GetFileName(raw ?? "");
        if (string.IsNullOrWhiteSpace(name)
            || name.Contains("..", StringComparison.Ordinal)
            || name.IndexOfAny(new[] { '/', '\\' }) >= 0)
        {
            throw new InvalidOperationException(
                "model_filename không hợp lệ (chỉ basename GGUF).");
        }
        return name;
    }

    public static RoomConfig FromJson(JsonElement root)
    {
        JsonElement cfg = root;
        if (root.TryGetProperty("room_config", out var rc))
            cfg = rc;

        string? S(string name) =>
            cfg.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
                ? el.GetString() : null;

        long N(string name) =>
            cfg.TryGetProperty(name, out var el) && el.TryGetInt64(out var value)
                ? Math.Max(0, value) : 0;

        var domains = new List<string>();
        if (cfg.TryGetProperty("allowed_domains", out var ad)
            && ad.ValueKind == JsonValueKind.Array)
        {
            foreach (var d in ad.EnumerateArray())
            {
                var s = d.GetString();
                if (!string.IsNullOrWhiteSpace(s))
                    domains.Add(s);
            }
        }

        return new RoomConfig
        {
            ModelId = S("model_id"),
            ModelUrl = S("model_url"),
            ModelSha256 = S("model_sha256"),
            ModelFilename = S("model_filename"),
            RuntimeUrl = S("runtime_url"),
            RuntimeSha256 = S("runtime_sha256"),
            RuntimeId = S("runtime_id"),
            ModelGeneration = N("model_generation"),
            LlamaServerExeSha256 = S("llama_server_exe_sha256"),
            LlamaServerImplDllSha256 = S("llama_server_impl_dll_sha256"),
            AllowedDomains = domains,
        };
    }
}
